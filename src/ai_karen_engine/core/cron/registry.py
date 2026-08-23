"""Cron job registry and specification.

All pg_cron responsibilities.
Cron may enqueue, refresh, or cleanup deterministic data.
Cron may NOT invoke LLM, execute agents, route providers, or run plugins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional


class JobAction(str, Enum):
    ENQUEUE = "enqueue"
    REFRESH = "refresh"
    CLEANUP = "cleanup"


class JobOwner(str, Enum):
    MEMORY = "memory"
    STORAGE = "storage"
    RUNTIME = "runtime"
    NOTIFICATIONS = "notifications"
    ANALYTICS = "analytics"
    PLATFORM = "platform"


@dataclass(frozen=True)
class CronJobSpec:
    name: str
    default_cadence: str
    action: JobAction
    owner: JobOwner
    description: str = ""
    timeout_seconds: int = 300


CRON_REGISTRY: Dict[str, CronJobSpec] = {
    "artifact_reconciliation": CronJobSpec(
        name="artifact_reconciliation",
        default_cadence="*/10 * * * *",
        action=JobAction.ENQUEUE,
        owner=JobOwner.STORAGE,
        description="Enqueue artifact reconciliation jobs.",
    ),
    "expired_idempotency_purge": CronJobSpec(
        name="expired_idempotency_purge",
        default_cadence="0 * * * *",
        action=JobAction.CLEANUP,
        owner=JobOwner.PLATFORM,
        description="Purge expired idempotency records.",
    ),
    "analytics_rollup": CronJobSpec(
        name="analytics_rollup",
        default_cadence="0 * * * *",
        action=JobAction.ENQUEUE,
        owner=JobOwner.ANALYTICS,
        description="Enqueue analytics rollup jobs.",
    ),
    "memory_consolidation": CronJobSpec(
        name="memory_consolidation",
        default_cadence="0 */6 * * *",
        action=JobAction.ENQUEUE,
        owner=JobOwner.MEMORY,
        description="Enqueue memory consolidation jobs.",
    ),
    "retention_evaluation": CronJobSpec(
        name="retention_evaluation",
        default_cadence="0 0 * * *",
        action=JobAction.CLEANUP,
        owner=JobOwner.PLATFORM,
        description="Evaluate and enqueue retention cleanup.",
    ),
    "temp_record_purge": CronJobSpec(
        name="temp_record_purge",
        default_cadence="0 0 * * *",
        action=JobAction.CLEANUP,
        owner=JobOwner.PLATFORM,
        description="Purge temporary records.",
    ),
    "materialized_view_refresh": CronJobSpec(
        name="materialized_view_refresh",
        default_cadence="0 * * * *",
        action=JobAction.REFRESH,
        owner=JobOwner.ANALYTICS,
        description="Refresh materialized views.",
    ),
}


def get_cron_job(name: str) -> CronJobSpec:
    if name not in CRON_REGISTRY:
        raise ValueError(f"Unknown cron job: {name!r}")
    return CRON_REGISTRY[name]


def list_cron_jobs(owner: Optional[JobOwner] = None) -> List[CronJobSpec]:
    jobs = list(CRON_REGISTRY.values())
    if owner:
        jobs = [job for job in jobs if job.owner == owner]
    return jobs
