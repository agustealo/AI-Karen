"""CK-07 runtime-owned durable admission and leased stream finality.

The canonical ChatRuntime executes the model. This coordinator only maintains
the durable run identity and guards the transport terminal against stale leases.
No SDK provider, prompt, memory store or duplicate executor is introduced.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Optional

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.persistence.repositories.chat_run_repository import (
    ChatRunLease,
    SqlChatRunRepository,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    get_conversation_runtime_gateway,
)

logger = logging.getLogger(__name__)


def _heartbeat_seconds() -> int:
    return get_runtime_settings().timeouts.chat_run_heartbeat_seconds


class ChatRunConflict(Exception):
    """Scoped transport identity has already been admitted."""


class ChatRunLeaseLost(Exception):
    """This execution is no longer authorized to report success."""


class ChatRunCoordinator:
    """Runtime authority for one canonical run record and fenced stream."""

    def __init__(self, repository: Optional[SqlChatRunRepository] = None) -> None:
        self._repository = repository or SqlChatRunRepository()

    async def admit(self, context: ChatExecutionContext, run_id: str) -> ChatRunLease:
        context.require_authenticated_user()
        # Reauthorize against the canonical repository at run-admission time.
        # Ingress verification alone must not become the execution authority.
        await get_conversation_runtime_gateway().require_owned_conversation(context)
        lease = await self._repository.admit(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=context.require_conversation_id(),
            transport_run_id=run_id,
            request_id=context.request_id or context.correlation_id,
            correlation_id=context.correlation_id,
        )
        if lease is None:
            raise ChatRunConflict("chat_run_already_exists")
        return lease

    async def stream(
        self,
        chunks: AsyncIterator[ChatStreamChunk],
        *,
        lease: ChatRunLease,
    ) -> AsyncIterator[ChatStreamChunk]:
        """Renew while a model awaits I/O; commit terminal BEFORE forwarding it.

        A heartbeat timer works even if the model has not yielded a token. A
        failed/expired token cancels the active upstream await rather than
        allowing an unowned model result to announce completion.
        """
        terminal = False
        next_chunk: Optional[asyncio.Task[ChatStreamChunk]] = None
        try:
            while True:
                next_chunk = asyncio.create_task(anext(chunks))
                while not next_chunk.done():
                    done, _ = await asyncio.wait(
                        {next_chunk}, timeout=_heartbeat_seconds()
                    )
                    if not done and not await self._repository.renew(lease):
                        raise ChatRunLeaseLost("chat_run_lease_lost")
                try:
                    chunk = await next_chunk
                except StopAsyncIteration:
                    break
                finally:
                    next_chunk = None

                if chunk.type == ChatStreamEventType.ERROR:
                    if not await self._repository.finish(
                        lease, status="failed", error_code="CHAT_RUNTIME_ERROR"
                    ):
                        raise ChatRunLeaseLost("chat_run_lease_lost")
                    terminal = True
                    yield chunk
                    break

                if chunk.type == ChatStreamEventType.COMPLETE:
                    meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
                    gated = meta.get("status") == "gate" or meta.get(
                        "error_code"
                    ) == "CHAT_RUNTIME_GATED"
                    status = "failed" if gated else "completed"
                    if not await self._repository.finish(
                        lease,
                        status=status,
                        error_code="CHAT_RUNTIME_GATED" if gated else None,
                    ):
                        raise ChatRunLeaseLost("chat_run_lease_lost")
                    terminal = True
                    if gated:
                        yield ChatStreamChunk(
                            type=ChatStreamEventType.ERROR,
                            content="Chat execution was not authorized to complete.",
                            correlation_id=lease.correlation_id,
                            metadata={"error_code": "CHAT_RUNTIME_GATED"},
                        )
                    else:
                        yield chunk
                    break

                yield chunk

            if not terminal:
                terminal = await self._repository.finish(
                    lease,
                    status="failed",
                    error_code="CHAT_SSE_MISSING_TERMINAL",
                )
                raise ChatRunLeaseLost("chat_run_missing_terminal")
        except BaseException as exc:
            # Connection cancellation must not become a successful assistant
            # turn. The runtime generator itself owns provider cleanup.
            if not terminal:
                try:
                    await self._repository.finish(
                        lease,
                        status="cancelled" if isinstance(
                            exc, (asyncio.CancelledError, GeneratorExit)
                        ) else "failed",
                        error_code=(
                            "CHAT_STREAM_CANCELLED"
                            if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                            else "CHAT_RUN_LEASE_LOST"
                        ),
                    )
                except Exception as cleanup_exc:
                    logger.error(
                        "Chat run terminal cleanup failed",
                        extra={
                            "execution_id": lease.execution_id,
                            "correlation_id": lease.correlation_id,
                            "error_type": type(cleanup_exc).__name__,
                        },
                    )
            raise
        finally:
            if next_chunk is not None and not next_chunk.done():
                next_chunk.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_chunk
            with suppress(Exception):
                await chunks.aclose()


def get_chat_run_coordinator() -> ChatRunCoordinator:
    """Construct a stateless coordinator; PostgreSQL is the only shared store."""
    return ChatRunCoordinator()
