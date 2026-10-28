"""CK-07 runtime-owned durable admission and leased stream finality.

The canonical ChatRuntime executes the model. This coordinator only maintains
the durable run identity and guards the transport terminal against stale leases.
No SDK provider, prompt, memory store or duplicate executor is introduced.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Optional

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.logging import get_structured_logger
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


class ChatRunCancellationRequested(Exception):
    """A different authorized worker/request has requested this run to stop."""


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

    async def request_cancel(
        self, context: ChatExecutionContext, *, run_id: str,
    ) -> Optional[str]:
        """Verify owner again; atomically signal the ONE scoped execution."""
        context.require_authenticated_user()
        await get_conversation_runtime_gateway().require_owned_conversation(context)
        return await self._repository.request_cancel(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=context.require_conversation_id(),
            transport_run_id=run_id,
        )

    async def read_status(
        self, context: ChatExecutionContext, *, run_id: str,
    ) -> Optional[dict[str, Any]]:
        """Authenticate ownership again, then read the canonical run row."""
        context.require_authenticated_user()
        await get_conversation_runtime_gateway().require_owned_conversation(context)
        return await self._repository.read_status(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=context.require_conversation_id(),
            transport_run_id=run_id,
        )

    async def append_observed_event(
        self, lease: ChatRunLease, event: dict[str, Any],
    ) -> int:
        """Persist only an already-projected event, never raw model metadata."""
        return await self._repository.append_projected_event(
            lease, event=event,
        )

    async def read_observed_events(
        self, context: ChatExecutionContext, *, run_id: str,
        after: int = 0, limit: int = 50,
    ) -> Optional[dict[str, Any]]:
        """Reauthorize an owner; read persisted observations without running AI."""
        context.require_authenticated_user()
        await get_conversation_runtime_gateway().require_owned_conversation(context)
        return await self._repository.read_projected_events(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=context.require_conversation_id(),
            transport_run_id=run_id,
            after=after,
            limit=limit,
        )

    async def fail_unstarted_event_journal(
        self, lease: ChatRunLease,
    ) -> bool:
        """Only a journal failure before inference may fail the owned run."""
        return await self._repository.finish(
            lease,
            status="failed",
            error_code="CHAT_EVENT_JOURNAL_UNAVAILABLE",
        )

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
        last_heartbeat = time.monotonic()

        async def require_active_lease() -> None:
            if await self._repository.renew(lease):
                return
            if await self._repository.cancel_requested(lease):
                raise ChatRunCancellationRequested("chat_run_cancel_requested")
            # Atomic transcript commit may already have completed the run.
            # Continue waiting for its canonical COMPLETE receipt, and
            # validate both message identities before RUN_FINISHED.
            if await self._repository.completed(lease):
                return
            raise ChatRunLeaseLost("chat_run_lease_lost")

        async def close_upstream(*, strict: bool = False) -> None:
            nonlocal next_chunk
            # Stop the actual model generator before confirming its terminal
            # cancellation. A DB intent alone is not a completed stop.
            if next_chunk is not None:
                if not next_chunk.done():
                    next_chunk.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_chunk
                next_chunk = None
            if strict:
                # An upstream cleanup failure cannot be counted as a
                # confirmed cancelled execution.
                await chunks.aclose()
            else:
                with suppress(Exception):
                    await chunks.aclose()

        try:
            while True:
                next_chunk = asyncio.create_task(anext(chunks))
                while not next_chunk.done():
                    done, _ = await asyncio.wait(
                        {next_chunk}, timeout=_heartbeat_seconds()
                    )
                    if not done:
                        await require_active_lease()
                        last_heartbeat = time.monotonic()
                try:
                    chunk = await next_chunk
                except StopAsyncIteration:
                    break
                finally:
                    next_chunk = None

                # Fast streams need periodic checks as well as blocked-provider
                # timeouts; otherwise cancellation may be delayed indefinitely.
                if time.monotonic() - last_heartbeat >= _heartbeat_seconds():
                    await require_active_lease()
                    last_heartbeat = time.monotonic()

                # A stopped task can yield one last chunk while stop wins the
                # finality race. Do not project its completion or extra data.
                if chunk.type in {ChatStreamEventType.COMPLETE, ChatStreamEventType.ERROR}:
                    if await self._repository.cancel_requested(lease):
                        raise ChatRunCancellationRequested("chat_run_cancel_requested")

                if chunk.type == ChatStreamEventType.ERROR:
                    if not await self._repository.finish(
                        lease, status="failed", error_code="CHAT_RUNTIME_ERROR"
                    ):
                        if await self._repository.cancel_requested(lease):
                            raise ChatRunCancellationRequested("chat_run_cancel_requested")
                        raise ChatRunLeaseLost("chat_run_lease_lost")
                    terminal = True
                    yield chunk
                    break

                if chunk.type == ChatStreamEventType.COMPLETE:
                    meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
                    gated = meta.get("status") == "gate" or meta.get(
                        "error_code"
                    ) == "CHAT_RUNTIME_GATED"
                    persisted = meta.get("transcript_persistence_status") in {
                        "persisted", "already_persisted",
                    }
                    error_code = (
                        "CHAT_RUNTIME_GATED" if gated else
                        "CHAT_TRANSCRIPT_NOT_PERSISTED" if not persisted else None
                    )
                    if not error_code:
                        user_message_id = meta.get("user_message_id")
                        assistant_message_id = meta.get("assistant_message_id")
                        committed = (
                            isinstance(user_message_id, str)
                            and isinstance(assistant_message_id, str)
                            and await self._repository.committed_turn(
                                lease,
                                user_message_id=user_message_id,
                                assistant_message_id=assistant_message_id,
                            )
                        )
                        if not committed:
                            if await self._repository.cancel_requested(lease):
                                raise ChatRunCancellationRequested("chat_run_cancel_requested")
                            raise ChatRunLeaseLost("chat_run_atomic_commit_not_verified")
                    elif not await self._repository.finish(
                        lease, status="failed", error_code=error_code,
                    ):
                        if await self._repository.cancel_requested(lease):
                            raise ChatRunCancellationRequested("chat_run_cancel_requested")
                        raise ChatRunLeaseLost("chat_run_lease_lost")
                    terminal = True
                    if error_code:
                        yield ChatStreamChunk(
                            type=ChatStreamEventType.ERROR,
                            content=(
                                "Chat execution was not authorized to complete."
                                if gated else
                                "Chat response could not be confirmed in saved history."
                            ),
                            correlation_id=lease.correlation_id,
                            metadata={"error_code": error_code},
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
                if not terminal and await self._repository.cancel_requested(lease):
                    raise ChatRunCancellationRequested("chat_run_cancel_requested")
                raise ChatRunLeaseLost("chat_run_missing_terminal")
        except ChatRunCancellationRequested:
            await close_upstream(strict=True)
            if not await self._repository.finish(
                lease, status="cancelled", error_code="CHAT_STREAM_CANCELLED",
            ):
                raise ChatRunLeaseLost("chat_run_lease_lost")
            terminal = True
            get_structured_logger().log_event(
                event="chat_run_cancelled",
                user_id=lease.user_id,
                details={
                    "tenant_id": lease.tenant_id,
                    "conversation_id": lease.conversation_id,
                    "execution_id": lease.execution_id,
                    "request_id": lease.request_id,
                    "correlation_id": lease.correlation_id,
                    "status": "cancelled",
                },
            )
            raise
        except BaseException as exc:
            # Connection cancellation must not become a successful assistant
            # turn. The runtime generator itself owns provider cleanup.
            if not terminal:
                await close_upstream(strict=True)
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
            await close_upstream()


def get_chat_run_coordinator() -> ChatRunCoordinator:
    """Construct a stateless coordinator; PostgreSQL is the only shared store."""
    return ChatRunCoordinator()
