"""Bounded, host-owned supervised inbox execution.

Only verified, durably admitted events may enter this process-local queue.
The database claim is the source of truth; the queue is an optimization, not
an authority or a durable second store. Startup never scans tenant connections
or restores transport sessions. Expired claims are eligible for explicit
governed reconciliation by their original tenant owner.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from ai_karen_engine.persistence.repositories.channel_repository import (
    InboundAdmission,
    SqlChannelRepository,
)
from ai_karen_engine.services.channels.execution import ChannelExecutionService
from ai_karen_engine.services.channels.delivery import ChannelDeliveryService

logger = logging.getLogger(__name__)


class ChannelInboxWorker:
    """Process admitted inbox IDs with bounded concurrency and lease fencing."""

    def __init__(
        self, *,
        repository: SqlChannelRepository,
        execution: ChannelExecutionService,
        max_inflight: int = 4,
        lease_seconds: int = 90,
        max_scheduled: int = 64,
        dispatch_outbox: Callable[..., Awaitable[bool]] | None = None,
    ) -> None:
        if not 1 <= max_inflight <= 64:
            raise ValueError("Channel worker concurrency must be 1..64")
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Channel worker lease must be 3..3600 seconds")
        if not max_inflight <= max_scheduled <= 4096:
            raise ValueError("Channel worker scheduled budget must be bounded")
        self._repository = repository
        self._execution = execution
        self._lease_seconds = lease_seconds
        self._max_scheduled = max_scheduled
        self._dispatch_outbox = dispatch_outbox
        self._limit = asyncio.Semaphore(max_inflight)
        self._tasks: set[asyncio.Task[None]] = set()
        self._scheduled: set[tuple[str, str]] = set()
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        if self._tasks:
            raise RuntimeError("Channel worker has unfinished tasks")
        self._running = True

    async def submit(self, admission: InboundAdmission) -> bool:
        """Schedule one already-persisted receipt, never trust a native payload.

        Idempotent webhook replay may submit the same reference twice. This
        process deduplicates locally; SQL remains authoritative across hosts.
        """
        if not self._running:
            return False
        if not isinstance(admission, InboundAdmission):
            raise TypeError("Channel worker requires a canonical admission receipt")
        key = (admission.tenant_id, admission.inbox_id)
        if key in self._scheduled:
            return False
        if len(self._scheduled) >= self._max_scheduled:
            logger.warning(
                "channel.worker.capacity_exhausted",
                extra={"tenant_id": admission.tenant_id,
                       "inbox_id": admission.inbox_id},
            )
            return False
        self._scheduled.add(key)
        task = asyncio.create_task(self._run(admission, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(
        self, admission: InboundAdmission, key: tuple[str, str],
    ) -> None:
        try:
            async with self._limit:
                if not self._running:
                    return
                claimed = await self._repository.claim_inbound(
                    tenant_id=admission.tenant_id,
                    inbox_id=admission.inbox_id,
                    lease_seconds=self._lease_seconds,
                )
                if claimed is None:
                    return
                token, current = claimed
                if (
                    current.tenant_id != admission.tenant_id
                    or current.inbox_id != admission.inbox_id
                    or current.user_id != admission.user_id
                    or current.binding_id != admission.binding_id
                ):
                    # A mismatch is a security failure. Do not execute or
                    # release a possibly foreign claim.
                    logger.error(
                        "channel.worker.claim_identity_mismatch",
                        extra={"tenant_id": admission.tenant_id,
                               "inbox_id": admission.inbox_id},
                    )
                    return
                committed = await self._execution.execute_claimed_text(
                    tenant_id=admission.tenant_id,
                    inbox_id=admission.inbox_id,
                    claim_token=token,
                    lease_seconds=self._lease_seconds,
                )
                if committed is True and self._dispatch_outbox is not None and self._running:
                    # Deterministic, inbox-bound delivery identity is owned by
                    # ChannelExecutionService. Re-read persisted preflight
                    # instead of trusting a provider or the incoming receipt.
                    delivery_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"karen-channel-delivery:{admission.inbox_id}",
                    ))
                    preflight = await self._repository.get_delivery_preflight(
                        tenant_id=admission.tenant_id, delivery_id=delivery_id,
                    )
                    if preflight is None or preflight.user_id != admission.user_id:
                        logger.warning(
                            "channel.worker.outbox_preflight_unavailable",
                            extra={"tenant_id": admission.tenant_id,
                                   "inbox_id": admission.inbox_id,
                                   "delivery_id": delivery_id},
                        )
                        return
                    session_id = ChannelDeliveryService._session_id(
                        tenant_id=admission.tenant_id, user_id=preflight.user_id,
                        connection_id=preflight.connection_id,
                        external_conversation_id=preflight.external_conversation_id,
                    )
                    await self._dispatch_outbox(
                        tenant_id=admission.tenant_id,
                        delivery_id=delivery_id,
                        user_id=preflight.user_id,
                        session_id=session_id,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # ExecutionService owns durable failure; an unavailable database
            # leaves the lease for governed reconciliation.
            logger.warning(
                "channel.worker.execution_failed",
                extra={"tenant_id": admission.tenant_id,
                       "inbox_id": admission.inbox_id,
                       "error_type": type(exc).__name__},
            )
        finally:
            self._scheduled.discard(key)

    async def shutdown(self) -> None:
        """Refuse new admission, cancel work and await all task termination."""
        self._running = False
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._scheduled.clear()


__all__ = ["ChannelInboxWorker"]
