"""Automation definition service.

Owns validation and CRUD orchestration for saved tasks and cron commitments.
Persistence is delegated to SqlAutomationRepository; AI execution is not owned
here.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, List, Optional

from croniter import croniter

from ai_karen_engine.agents import get_agent_integration_service
from ai_karen_engine.core.runtime.task_output_verification import validate_contract
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)


class AutomationDefinitionError(ValueError):
    """Invalid automation definition."""


class AutomationNotFoundError(LookupError):
    """Tenant-scoped automation definition does not exist."""


def _require_identity(user: UserData) -> None:
    if not str(user.user_id or "").strip():
        raise AutomationDefinitionError("Authenticated user_id is required")
    if not str(user.tenant_id or "").strip() or str(user.tenant_id) == "default":
        raise AutomationDefinitionError("Explicit tenant_id is required")


def slugify_task_type(name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "general_task"


def _validated_timezone(timezone_id: str) -> ZoneInfo:
    """Timezone is a scheduling preference, not evidence of physical location."""
    raw = str(timezone_id or "").strip()
    if not raw or len(raw) > 128:
        raise AutomationDefinitionError("A valid IANA timezone_id is required")
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise AutomationDefinitionError("Unrecognized IANA timezone_id") from exc


def _daily_wall_time(schedule: str) -> Optional[clock_time]:
    """Recognize a strict once-daily cron (not a general calendar expression)."""
    fields = schedule.split()
    if (
        len(fields) != 5
        or fields[2:] != ["*", "*", "*"]
        or not fields[0].isdigit()
        or not fields[1].isdigit()
    ):
        return None
    minute, hour = int(fields[0]), int(fields[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return clock_time(hour=hour, minute=minute)


def next_cron_run(
    schedule: str,
    *,
    now: Optional[datetime] = None,
    timezone_id: str = "UTC",
) -> datetime:
    """Return next absolute UTC occurrence of an IANA-local recurrence.

    For a named zone, a daily nonexistent DST spring time is skipped rather
    than silently shifted to another hour. An ambiguous autumn wall time runs
    once on its first (fold=0) occurrence. Legacy UTC non-daily expressions
    retain croniter behavior. Non-daily IANA schedules fail closed until their
    local recurrence semantics can be independently verified.
    """
    if not croniter.is_valid(schedule):
        raise AutomationDefinitionError("Invalid cron expression")
    zone = _validated_timezone(timezone_id)
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        raise AutomationDefinitionError("Scheduler clock must include UTC offset")
    base_utc = base.astimezone(timezone.utc)
    wall_time = _daily_wall_time(schedule)
    if wall_time is None:
        if zone.key != "UTC":
            raise AutomationDefinitionError(
                "Named IANA timezones currently require a once-daily schedule"
            )
        return croniter(schedule, base_utc).get_next(datetime).astimezone(timezone.utc)

    day = base_utc.astimezone(zone).date()
    for offset in range(370):
        wall = datetime.combine(day + timedelta(days=offset), wall_time)
        candidate = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
        # ZoneInfo permits representing nonexistent local times. Validate
        # round-trip to avoid moving 02:30 to 03:30 on a spring-forward day.
        if candidate.astimezone(zone).replace(tzinfo=None) != wall:
            continue
        if candidate > base_utc:
            return candidate
    raise AutomationDefinitionError("Could not resolve a valid next occurrence")


class AutomationDefinitionService:
    def __init__(self, repository: Optional[SqlAutomationRepository] = None) -> None:
        self._repository = repository or get_automation_repository()

    async def _normalize_task_record(
        self, payload: Dict[str, Any], *, record_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One validation and agent registry path for UI and chat task authors."""
        primary_agent = str(payload.get("primaryAgent") or "").strip()
        if not primary_agent:
            raise AutomationDefinitionError("primaryAgent is required")

        # Compatibility metadata lookup only. Execution authority remains ChatRuntime.
        integration = get_agent_integration_service()
        await integration.initialize()
        if not await integration.get_agent_info(primary_agent):
            raise AutomationNotFoundError(f"Primary agent {primary_agent} not found")

        sub_agents = list(payload.get("subAgents") or [])
        for sub_agent in sub_agents:
            agent_id = str(sub_agent.get("agentId") or "").strip()
            if agent_id and not await integration.get_agent_info(agent_id):
                raise AutomationNotFoundError(f"Sub-agent {agent_id} not found")

        record = {
            "id": record_id or f"task_{uuid.uuid4().hex[:12]}",
            "name": str(payload.get("name") or "").strip(),
            "description": str(payload.get("description") or "").strip(),
            "acceptanceCriteria": str(payload.get("acceptanceCriteria") or "").strip(),
            "verificationContract": validate_contract(payload.get("verificationContract")),
            "primaryAgent": primary_agent,
            "primaryAgentInstructions": str(
                payload.get("primaryAgentInstructions") or ""
            ),
            "taskType": str(
                payload.get("taskType")
                or slugify_task_type(str(payload.get("name") or ""))
            ),
            "subAgents": sub_agents,
        }
        if not record["name"] or not record["description"]:
            raise AutomationDefinitionError("Task name and description are required")
        if len(record["acceptanceCriteria"]) > 4000:
            raise AutomationDefinitionError("Acceptance criteria must not exceed 4000 characters")

        return record

    async def create_task(
        self,
        payload: Dict[str, Any],
        *,
        user: UserData,
    ) -> Dict[str, Any]:
        _require_identity(user)
        record = await self._normalize_task_record(payload)
        return await self._repository.create_task(
            tenant_id=str(user.tenant_id),
            created_by=str(user.user_id),
            record=record,
        )

    async def create_chat_recurring_task(
        self,
        *,
        user: UserData,
        purpose: str,
        primary_agent: str,
        hour_local: int,
        minute_local: int,
        timezone_id: str,
        conversation_id: str,
    ) -> Dict[str, Any]:
        """Authorize agent metadata then atomically commit a local daily task.

        The canonical PostgreSQL repository enforces transaction/replay ownership.
        A scheduled definition is not evidence of execution or news delivery.
        """
        _require_identity(user)
        purpose = " ".join(str(purpose or "").strip().split())
        if not purpose or len(purpose) > 500:
            raise AutomationDefinitionError("Task purpose must be 1-500 characters")
        if not 0 <= hour_local <= 23 or not 0 <= minute_local <= 59:
            raise AutomationDefinitionError("Local hour or minute is invalid")
        zone = _validated_timezone(timezone_id)
        if not str(conversation_id or "").strip():
            raise AutomationDefinitionError("An owner-scoped conversation identity is required")

        # REST and SSE mint a new request_id on each transport retry. A task
        # must never use that ephemeral ID to key a repeating side effect.
        # Treat an identical commitment in the same conversation as one
        # operation, including after a lost response; changed schedule,
        # instructions, agent or timezone form a distinct commitment.
        normalized_commitment = json.dumps(
            {
                "purpose": purpose,
                "primary_agent": primary_agent,
                "hour_local": hour_local,
                "minute_local": minute_local,
                "timezone_id": zone.key,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = ":".join((
            "karen-chat-recurring-v2", str(user.tenant_id), str(user.user_id),
            str(conversation_id), normalized_commitment,
        ))
        stable_key = uuid.uuid5(uuid.NAMESPACE_URL, identity).hex
        task_id = f"task_{stable_key}"
        cron_id = f"cron_{stable_key}"
        task = await self._normalize_task_record(
            {
                "name": purpose[:120],
                "description": purpose,
                "primaryAgent": primary_agent,
                "primaryAgentInstructions": purpose,
                "taskType": slugify_task_type(purpose[:80]),
            },
            record_id=task_id,
        )
        schedule = f"{minute_local} {hour_local} * * *"
        next_run_at = next_cron_run(schedule, timezone_id=zone.key)
        cron = {
            "id": cron_id,
            "taskName": task["name"],
            "schedule": schedule,
            "timezone_id": zone.key,
            "local_time": clock_time(hour_local, minute_local),
            "type": "Task",
            "targetId": task_id,
            "enabled": True,
            "action": "execute",
        }
        return await self._repository.create_chat_scheduled_task(
            tenant_id=str(user.tenant_id),
            created_by=str(user.user_id),
            task_record=task,
            cron_record=cron,
            next_run_at=next_run_at,
        )

    async def get_task(self, task_id: str, *, user: UserData) -> Dict[str, Any]:
        _require_identity(user)
        task = await self._repository.get_task(
            task_id, str(user.tenant_id), created_by=str(user.user_id)
        )
        if task is None:
            raise AutomationNotFoundError("Task not found")
        return task

    async def list_tasks(
        self,
        *,
        user: UserData,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        _require_identity(user)
        return await self._repository.list_tasks(
            str(user.tenant_id),
            status=status,
            agent_name=agent_name,
            created_by=str(user.user_id),
        )

    async def delete_task(self, task_id: str, *, user: UserData) -> None:
        _require_identity(user)
        if not await self._repository.delete_task(
            task_id, str(user.tenant_id), created_by=str(user.user_id)
        ):
            raise AutomationNotFoundError("Task not found")

    async def create_cron(
        self,
        payload: Dict[str, Any],
        *,
        user: UserData,
    ) -> Dict[str, Any]:
        _require_identity(user)
        job_type = str(payload.get("type") or "").strip()
        if job_type not in {"Task", "Job", "Sequence"}:
            raise AutomationDefinitionError("type must be Task, Job, or Sequence")
        action = str(payload.get("action") or "execute").strip().lower()
        if action not in {"execute", "enqueue"}:
            raise AutomationDefinitionError("action must be execute or enqueue")

        target_id = str(payload.get("targetId") or "").strip()
        if job_type == "Task":
            target = await self._repository.get_task(
                target_id, str(user.tenant_id), created_by=str(user.user_id)
            )
        else:
            target = await self._repository.get_job(
                target_id, str(user.tenant_id), created_by=str(user.user_id)
            )
        if target is None:
            raise AutomationNotFoundError("Automation target not found")

        schedule = str(payload.get("schedule") or "").strip()
        zone = _validated_timezone(str(payload.get("timezone_id") or "UTC"))
        next_run_at = next_cron_run(schedule, timezone_id=zone.key)
        local_time = _daily_wall_time(schedule)
        record = {
            "id": f"cron_{uuid.uuid4().hex[:12]}",
            "taskName": str(payload.get("taskName") or "").strip(),
            "schedule": schedule,
            "timezone_id": zone.key,
            "local_time": local_time,
            "type": job_type,
            "targetId": target_id,
            "enabled": bool(payload.get("enabled", True)),
            "action": action,
        }
        if not record["taskName"]:
            raise AutomationDefinitionError("taskName is required")
        return await self._repository.create_cron(
            tenant_id=str(user.tenant_id),
            created_by=str(user.user_id),
            record=record,
            next_run_at=next_run_at,
        )

    async def list_cron(self, *, user: UserData) -> List[Dict[str, Any]]:
        _require_identity(user)
        return await self._repository.list_cron(
            str(user.tenant_id), created_by=str(user.user_id)
        )

    async def delete_cron(self, cron_id: str, *, user: UserData) -> None:
        _require_identity(user)
        if not await self._repository.delete_cron(
            cron_id, str(user.tenant_id), created_by=str(user.user_id)
        ):
            raise AutomationNotFoundError("Cron job not found")

    async def toggle_cron(self, cron_id: str, *, user: UserData) -> Dict[str, Any]:
        _require_identity(user)
        current = await self._repository.get_cron(
            cron_id, str(user.tenant_id), created_by=str(user.user_id)
        )
        if current is None:
            raise AutomationNotFoundError("Cron job not found")
        next_run_at = next_cron_run(
            current["schedule"],
            timezone_id=current.get("timezone_id") or "UTC",
        )
        updated = await self._repository.toggle_cron(
            cron_id,
            str(user.tenant_id),
            next_run_at=next_run_at,
            created_by=str(user.user_id),
        )
        if updated is None:
            raise AutomationNotFoundError("Cron job not found")
        return updated

    async def task_summary(self, *, tenant_id: str) -> Dict[str, Any]:
        return await self._repository.task_summary(tenant_id)

    async def cron_summary(self, *, tenant_id: str) -> Dict[str, Any]:
        return await self._repository.cron_summary(tenant_id)


_definition_service: Optional[AutomationDefinitionService] = None


def get_automation_definition_service() -> AutomationDefinitionService:
    global _definition_service
    if _definition_service is None:
        _definition_service = AutomationDefinitionService()
    return _definition_service


__all__ = [
    "AutomationDefinitionError",
    "AutomationNotFoundError",
    "AutomationDefinitionService",
    "get_automation_definition_service",
    "next_cron_run",
    "slugify_task_type",
]
