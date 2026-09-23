"""Queue-claim lease maintenance for long-running automation work."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, TypeVar

from ai_karen_engine.services.automation.claim_lease import (
    ClaimLeaseLost,
    run_with_claim_heartbeat,
)
from ai_karen_engine.services.database.repositories.queue_client import (
    QueueClient,
    QueueItem,
)

_QUEUE_HEARTBEAT_SECONDS = 60.0
_ResultT = TypeVar("_ResultT")


class QueueClaimLost(ClaimLeaseLost):
    """Raised when durable queue work no longer owns its processing claim."""


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

    async def renew() -> bool:
        result = await client.renew_claim(
            item.queue,
            item.id,
            claim_token=claim_token,
        )
        return bool(result.success and result.data)

    return await run_with_claim_heartbeat(
        operation,
        renew=renew,
        heartbeat_seconds=heartbeat_seconds,
        lost_error=QueueClaimLost,
        lost_message="Queue processing claim could not be renewed",
    )


__all__ = ["QueueClaimLost", "run_with_queue_claim_heartbeat"]
