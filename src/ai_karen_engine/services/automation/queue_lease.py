"""Queue-claim lease maintenance for long-running automation work."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from ai_karen_engine.services.database.repositories.queue_client import (
    QueueClient,
    QueueItem,
)

_QUEUE_HEARTBEAT_SECONDS = 60.0
_ResultT = TypeVar("_ResultT")


class QueueClaimLost(RuntimeError):
    """Raised when durable work no longer owns its queue processing claim."""


async def run_with_queue_claim_heartbeat(
    client: QueueClient,
    item: QueueItem,
    operation: Coroutine[Any, Any, _ResultT],
    *,
    heartbeat_seconds: float = _QUEUE_HEARTBEAT_SECONDS,
) -> _ResultT:
    """Run work while renewing its queue claim, cancelling if ownership is lost."""
    claim_token = str(item.claim_token or "").strip()
    if not claim_token:
        operation.close()
        raise QueueClaimLost("Queue item has no claim token")
    if heartbeat_seconds <= 0:
        operation.close()
        raise ValueError("heartbeat_seconds must be positive")

    task = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if task in done:
                return await task

            renewal = await client.renew_claim(
                item.queue,
                item.id,
                claim_token=claim_token,
            )
            if not renewal.success or not renewal.data:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise QueueClaimLost(
                    renewal.error or "Queue processing claim could not be renewed"
                )
    except BaseException:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        raise


__all__ = ["QueueClaimLost", "run_with_queue_claim_heartbeat"]
