"""Cron-claim lease maintenance for long-running scheduled execution."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Dict, TypeVar

from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
)
from ai_karen_engine.services.automation.claim_lease import (
    ClaimLeaseLost,
    run_with_claim_heartbeat,
)

_CRON_HEARTBEAT_SECONDS = 120.0
_ResultT = TypeVar("_ResultT")


class CronClaimLost(ClaimLeaseLost):
    """Raised when a scheduled occurrence no longer owns its cron claim."""


async def run_with_cron_claim_heartbeat(
    repository: SqlAutomationRepository,
    job: Dict[str, Any],
    operation: Coroutine[Any, Any, _ResultT],
    *,
    heartbeat_seconds: float = _CRON_HEARTBEAT_SECONDS,
) -> _ResultT:
    """Run one cron occurrence while renewing its durable scheduler claim."""
    cron_id = str(job.get("id") or "").strip()
    claim_token = str(job.get("claim_token") or "").strip()
    if not cron_id or not claim_token:
        operation.close()
        raise CronClaimLost("Cron occurrence has no durable claim")

    async def renew() -> bool:
        return await repository.renew_cron_claim(cron_id, claim_token)

    return await run_with_claim_heartbeat(
        operation,
        renew=renew,
        heartbeat_seconds=heartbeat_seconds,
        lost_error=CronClaimLost,
        lost_message="Cron scheduler claim could not be renewed",
    )


__all__ = ["CronClaimLost", "run_with_cron_claim_heartbeat"]
