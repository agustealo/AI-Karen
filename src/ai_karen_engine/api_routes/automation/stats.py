"""Tenant-scoped automation dashboard statistics."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.api_routes.automation.cron import get_cron_summary
from ai_karen_engine.api_routes.automation.tasks import get_tasks_summary
from ai_karen_engine.services.job_service import JobService, get_job_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation/stats", tags=["automation-stats"])


@router.get("/")
async def get_automation_stats(
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
) -> Dict[str, Any]:
    """Return dashboard truth only for the authenticated tenant.

    Agent catalog/lifecycle data is intentionally absent because the legacy
    agent registry is installation-wide control-plane state. This tenant
    dashboard exposes only metrics owned by tenant-scoped automation sources.
    """
    try:
        tenant_id = str(user.tenant_id)
        tasks_summary = await get_tasks_summary(tenant_id)
        cron_summary = await get_cron_summary(tenant_id)
        jobs = await job_service.list_jobs(user)

        return {
            "activeTasks": str(tasks_summary["active_tasks"]),
            "tasksToday": str(tasks_summary["tasks_run_today"]),
            "definedSequences": str(len(jobs)),
            "nextJob": cron_summary["next_job"] or "None Scheduled",
            "nextJobTime": cron_summary["next_job_time"] or "N/A",
            "details": {
                "tasks": tasks_summary,
                "cron": cron_summary,
                "total_sequences": len(jobs),
            },
        }
    except Exception as exc:
        logger.exception(
            "automation.stats.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Automation statistics are unavailable",
        ) from exc
