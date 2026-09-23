"""Canonical PostgreSQL automation repository.

Owns durable task, job, cron, and scheduler state. HTTP routes and runtime
workers delegate here rather than maintaining process-local or file-backed
registries. Schema creation is migration-owned.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

_CRON_LEASE_SECONDS = 900


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _task_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    last_run = data.get("last_run_at")
    return {
        "id": data["task_id"],
        "name": data["name"],
        "description": data["description"],
        "primaryAgent": data["primary_agent"],
        "primaryAgentInstructions": data["primary_agent_instructions"],
        "taskType": data["task_type"],
        "subAgents": list(data.get("sub_agents") or []),
        "lastRun": last_run.strftime("%Y-%m-%d %H:%M UTC") if last_run else None,
        "status": data["status"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "lastError": data.get("last_error"),
        "runCount": int(data.get("run_count") or 0),
        "runtimeTaskId": data.get("runtime_task_id"),
        "created_by": str(data["created_by"]),
        "tenant_id": str(data["tenant_id"]),
    }


def _job_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    return {
        "id": data["job_id"],
        "name": data["name"],
        "description": data["description"],
        "tasks": list(data.get("tasks") or []),
        "trigger": data["trigger"],
        "status": data["status"],
        "last_results": list(data.get("last_results") or []),
        "last_run": data.get("last_run_at"),
        "last_error": data.get("last_error"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "created_by": str(data["created_by"]),
        "tenant_id": str(data["tenant_id"]),
    }


def _cron_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    enabled = bool(data["enabled"])
    next_run = data["next_run_at"]
    return {
        "id": data["cron_id"],
        "taskName": data["task_name"],
        "schedule": data["schedule"],
        "type": data["job_type"],
        "targetId": data["target_id"],
        "enabled": enabled,
        "action": data["action"],
        "nextRun": next_run.isoformat() if enabled and next_run else "Disabled",
        "next_run_at": next_run,
        "last_run_at": data.get("last_run_at"),
        "last_error": data.get("last_error"),
        "claim_token": str(data["claim_token"]) if data.get("claim_token") else None,
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "created_by": str(data["created_by"]),
        "tenant_id": str(data["tenant_id"]),
    }


class SqlAutomationRepository:
    """Single durable source of truth for automation definitions and cron claims."""

    async def create_task(
        self,
        *,
        tenant_id: str,
        created_by: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.automation_tasks (
                        task_id, tenant_id, created_by, name, description,
                        primary_agent, primary_agent_instructions, task_type, sub_agents
                    ) VALUES (
                        :task_id, CAST(:tenant_id AS uuid), CAST(:created_by AS uuid),
                        :name, :description, :primary_agent,
                        :primary_agent_instructions, :task_type,
                        CAST(:sub_agents AS jsonb)
                    )
                    RETURNING *
                    """
                ),
                {
                    "task_id": record["id"],
                    "tenant_id": tenant_id,
                    "created_by": created_by,
                    "name": record["name"],
                    "description": record["description"],
                    "primary_agent": record["primaryAgent"],
                    "primary_agent_instructions": record.get("primaryAgentInstructions", ""),
                    "task_type": record["taskType"],
                    "sub_agents": json.dumps(record.get("subAgents") or []),
                },
            )
            return _task_row(result.mappings().one())

    async def get_task(self, task_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM public.automation_tasks
                    WHERE task_id = :task_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"task_id": task_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
            return _task_row(row) if row else None

    async def list_tasks(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["tenant_id = CAST(:tenant_id AS uuid)"]
        params: Dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if agent_name:
            clauses.append("primary_agent = :agent_name")
            params["agent_name"] = agent_name
        query = (
            "SELECT * FROM public.automation_tasks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC"
        )
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(text(query), params)
            return [_task_row(row) for row in result.mappings().all()]

    async def delete_task(self, task_id: str, tenant_id: str) -> bool:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM public.automation_tasks
                    WHERE task_id = :task_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING task_id
                    """
                ),
                {"task_id": task_id, "tenant_id": tenant_id},
            )
            return result.scalar_one_or_none() is not None

    async def mark_task_running(self, task_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_tasks
                    SET status = 'Running',
                        last_run_at = now(),
                        last_error = NULL,
                        run_count = run_count + 1,
                        updated_at = now()
                    WHERE task_id = :task_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING *
                    """
                ),
                {"task_id": task_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
            return _task_row(row) if row else None

    async def complete_task(
        self,
        task_id: str,
        tenant_id: str,
        *,
        status: str,
        last_error: Optional[str],
        runtime_task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_tasks
                    SET status = :status,
                        last_error = :last_error,
                        runtime_task_id = COALESCE(:runtime_task_id, runtime_task_id),
                        updated_at = now()
                    WHERE task_id = :task_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING *
                    """
                ),
                {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "status": status,
                    "last_error": last_error,
                    "runtime_task_id": runtime_task_id,
                },
            )
            row = result.mappings().one_or_none()
            return _task_row(row) if row else None

    async def task_summary(self, tenant_id: str) -> Dict[str, Any]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        count(*) AS total_definitions,
                        COALESCE(sum(run_count) FILTER (
                            WHERE updated_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                        ), 0) AS tasks_run_today,
                        count(*) FILTER (WHERE status = 'Running') AS active_tasks,
                        count(*) FILTER (WHERE status = 'Failed') AS failed_tasks
                    FROM public.automation_tasks
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"tenant_id": tenant_id},
            )
            row = result.mappings().one()
            return {key: int(row[key] or 0) for key in row.keys()}

    async def create_job(
        self,
        *,
        tenant_id: str,
        created_by: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        status = str(record.get("status") or "Pending")
        if status not in {"Pending", "Running", "Success", "Failed"}:
            status = "Pending"
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.automation_jobs (
                        job_id, tenant_id, created_by, name, description, tasks,
                        trigger, status, last_results, last_run_at, last_error,
                        created_at, updated_at
                    ) VALUES (
                        :job_id, CAST(:tenant_id AS uuid), CAST(:created_by AS uuid),
                        :name, :description, CAST(:tasks AS jsonb), :trigger,
                        :status, CAST(:last_results AS jsonb), :last_run_at,
                        :last_error, COALESCE(:created_at, now()),
                        COALESCE(:updated_at, now())
                    )
                    RETURNING *
                    """
                ),
                {
                    "job_id": record["id"],
                    "tenant_id": tenant_id,
                    "created_by": created_by,
                    "name": record["name"],
                    "description": record["description"],
                    "tasks": json.dumps(record.get("tasks") or []),
                    "trigger": record.get("trigger", "Manual Run"),
                    "status": status,
                    "last_results": json.dumps(record.get("last_results") or []),
                    "last_run_at": record.get("last_run"),
                    "last_error": record.get("last_error"),
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("updated_at"),
                },
            )
            return _job_row(result.mappings().one())

    async def get_job(self, job_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM public.automation_jobs
                    WHERE job_id = :job_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"job_id": job_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
            return _job_row(row) if row else None

    async def list_jobs(self, tenant_id: str) -> List[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM public.automation_jobs
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    ORDER BY created_at DESC
                    """
                ),
                {"tenant_id": tenant_id},
            )
            return [_job_row(row) for row in result.mappings().all()]

    async def delete_job(self, job_id: str, tenant_id: str) -> bool:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM public.automation_jobs
                    WHERE job_id = :job_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING job_id
                    """
                ),
                {"job_id": job_id, "tenant_id": tenant_id},
            )
            return result.scalar_one_or_none() is not None

    async def mark_job_running(self, job_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_jobs
                    SET status = 'Running',
                        last_run_at = now(),
                        last_error = NULL,
                        updated_at = now()
                    WHERE job_id = :job_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING *
                    """
                ),
                {"job_id": job_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
            return _job_row(row) if row else None

    async def complete_job(
        self,
        job_id: str,
        tenant_id: str,
        *,
        status: str,
        results: List[Dict[str, Any]],
        last_error: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_jobs
                    SET status = :status,
                        last_results = CAST(:results AS jsonb),
                        last_error = :last_error,
                        updated_at = now()
                    WHERE job_id = :job_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING *
                    """
                ),
                {
                    "job_id": job_id,
                    "tenant_id": tenant_id,
                    "status": status,
                    "results": json.dumps(results),
                    "last_error": last_error,
                },
            )
            row = result.mappings().one_or_none()
            return _job_row(row) if row else None

    async def create_cron(
        self,
        *,
        tenant_id: str,
        created_by: str,
        record: Dict[str, Any],
        next_run_at: datetime,
    ) -> Dict[str, Any]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.automation_cron_jobs (
                        cron_id, tenant_id, created_by, task_name, schedule,
                        job_type, target_id, enabled, action, next_run_at
                    ) VALUES (
                        :cron_id, CAST(:tenant_id AS uuid), CAST(:created_by AS uuid),
                        :task_name, :schedule, :job_type, :target_id,
                        :enabled, :action, :next_run_at
                    )
                    RETURNING *
                    """
                ),
                {
                    "cron_id": record["id"],
                    "tenant_id": tenant_id,
                    "created_by": created_by,
                    "task_name": record["taskName"],
                    "schedule": record["schedule"],
                    "job_type": record["type"],
                    "target_id": record["targetId"],
                    "enabled": record["enabled"],
                    "action": record["action"],
                    "next_run_at": next_run_at,
                },
            )
            return _cron_row(result.mappings().one())

    async def list_cron(self, tenant_id: str) -> List[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM public.automation_cron_jobs
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    ORDER BY created_at DESC
                    """
                ),
                {"tenant_id": tenant_id},
            )
            return [_cron_row(row) for row in result.mappings().all()]

    async def get_cron(self, cron_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM public.automation_cron_jobs
                    WHERE cron_id = :cron_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"cron_id": cron_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
            return _cron_row(row) if row else None

    async def delete_cron(self, cron_id: str, tenant_id: str) -> bool:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM public.automation_cron_jobs
                    WHERE cron_id = :cron_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING cron_id
                    """
                ),
                {"cron_id": cron_id, "tenant_id": tenant_id},
            )
            return result.scalar_one_or_none() is not None

    async def toggle_cron(
        self,
        cron_id: str,
        tenant_id: str,
        *,
        next_run_at: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_cron_jobs
                    SET enabled = NOT enabled,
                        next_run_at = CASE
                            WHEN enabled THEN next_run_at
                            ELSE :next_run_at
                        END,
                        updated_at = now()
                    WHERE cron_id = :cron_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    RETURNING *
                    """
                ),
                {
                    "cron_id": cron_id,
                    "tenant_id": tenant_id,
                    "next_run_at": next_run_at or _utcnow(),
                },
            )
            row = result.mappings().one_or_none()
            return _cron_row(row) if row else None

    async def cron_summary(self, tenant_id: str) -> Dict[str, Any]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        count(*) AS total_cron_jobs,
                        count(*) FILTER (WHERE enabled) AS enabled_cron_jobs,
                        min(next_run_at) FILTER (WHERE enabled) AS next_job_time
                    FROM public.automation_cron_jobs
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"tenant_id": tenant_id},
            )
            summary = dict(result.mappings().one())
            next_name = None
            if summary.get("next_job_time"):
                name_result = await session.execute(
                    text(
                        """
                        SELECT task_name
                        FROM public.automation_cron_jobs
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND enabled
                        ORDER BY next_run_at ASC
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": tenant_id},
                )
                next_name = name_result.scalar_one_or_none()
            return {
                "total_cron_jobs": int(summary["total_cron_jobs"] or 0),
                "enabled_cron_jobs": int(summary["enabled_cron_jobs"] or 0),
                "next_job": next_name,
                "next_job_time": (
                    summary["next_job_time"].isoformat()
                    if summary.get("next_job_time")
                    else None
                ),
            }

    async def claim_due_cron_jobs(
        self,
        worker_id: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        claim_token = uuid.uuid4()
        async with async_transaction_scope() as session:
            await session.execute(text("SELECT set_config('app.scheduler_worker', '1', true)"))
            result = await session.execute(
                text(
                    """
                    WITH due AS (
                        SELECT cron_id
                        FROM public.automation_cron_jobs
                        WHERE enabled
                          AND next_run_at <= now()
                          AND (claim_expires_at IS NULL OR claim_expires_at <= now())
                        ORDER BY next_run_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT :limit
                    )
                    UPDATE public.automation_cron_jobs AS jobs
                    SET claim_token = :claim_token,
                        claimed_by = :worker_id,
                        claimed_at = now(),
                        claim_expires_at = now() + make_interval(secs => :lease_seconds),
                        updated_at = now()
                    FROM due
                    WHERE jobs.cron_id = due.cron_id
                    RETURNING jobs.*
                    """
                ),
                {
                    "claim_token": claim_token,
                    "worker_id": worker_id,
                    "lease_seconds": _CRON_LEASE_SECONDS,
                    "limit": limit,
                },
            )
            return [_cron_row(row) for row in result.mappings().all()]

    async def renew_cron_claim(self, cron_id: str, claim_token: str) -> bool:
        """Extend a currently-owned cron claim without allowing expired reclaim."""
        async with async_transaction_scope() as session:
            await session.execute(text("SELECT set_config('app.scheduler_worker', '1', true)"))
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_cron_jobs
                    SET claim_expires_at = now() + make_interval(secs => :lease_seconds),
                        updated_at = now()
                    WHERE cron_id = :cron_id
                      AND claim_token = CAST(:claim_token AS uuid)
                      AND claim_expires_at > now()
                    RETURNING cron_id
                    """
                ),
                {
                    "cron_id": cron_id,
                    "claim_token": claim_token,
                    "lease_seconds": _CRON_LEASE_SECONDS,
                },
            )
            return result.scalar_one_or_none() is not None

    async def complete_cron_claim(
        self,
        cron_id: str,
        claim_token: str,
        *,
        next_run_at: datetime,
        last_error: Optional[str] = None,
    ) -> bool:
        async with async_transaction_scope() as session:
            await session.execute(text("SELECT set_config('app.scheduler_worker', '1', true)"))
            result = await session.execute(
                text(
                    """
                    UPDATE public.automation_cron_jobs
                    SET next_run_at = :next_run_at,
                        last_run_at = now(),
                        last_error = :last_error,
                        claim_token = NULL,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        updated_at = now()
                    WHERE cron_id = :cron_id
                      AND claim_token = CAST(:claim_token AS uuid)
                    RETURNING cron_id
                    """
                ),
                {
                    "cron_id": cron_id,
                    "claim_token": claim_token,
                    "next_run_at": next_run_at,
                    "last_error": last_error,
                },
            )
            return result.scalar_one_or_none() is not None


_automation_repository: Optional[SqlAutomationRepository] = None


def get_automation_repository() -> SqlAutomationRepository:
    global _automation_repository
    if _automation_repository is None:
        _automation_repository = SqlAutomationRepository()
    return _automation_repository


__all__ = ["SqlAutomationRepository", "get_automation_repository"]
