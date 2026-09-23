"""Automation definition service.

Owns validation and CRUD orchestration for saved tasks and cron commitments.
Persistence is delegated to SqlAutomationRepository; AI execution is not owned
here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from croniter import croniter

from ai_karen_engine.agents import get_agent_integration_service
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


def next_cron_run(schedule: str, *, now: Optional[datetime] = None) -> datetime:
    if not croniter.is_valid(schedule):
        raise AutomationDefinitionError("Invalid cron expression")
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return croniter(schedule, base).get_next(datetime)


class AutomationDefinitionService:
    def __init__(self, repository: Optional[SqlAutomationRepository] = None) -> None:
        self._repository = repository or get_automation_repository()

    async def create_task(
        self,
        payload: Dict[str, Any],
        *,
        user: UserData,
    ) -> Dict[str, Any]:
        _require_identity(user)
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
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "name": str(payload.get("name") or "").strip(),
            "description": str(payload.get("description") or "").strip(),
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
        return await self._repository.create_task(
            tenant_id=str(user.tenant_id),
            created_by=str(user.user_id),
            record=record,
        )

    async def get_task(self, task_id: str, *, user: UserData) -> Dict[str, Any]:
        _require_identity(user)
        task = await self._repository.get_task(task_id, str(user.tenant_id))
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
        )

    async def delete_task(self, task_id: str, *, user: UserData) -> None:
        _require_identity(user)
        if not await self._repository.delete_task(task_id, str(user.tenant_id)):
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
            target = await self._repository.get_task(target_id, str(user.tenant_id))
        else:
            target = await self._repository.get_job(target_id, str(user.tenant_id))
        if target is None:
            raise AutomationNotFoundError("Automation target not found")

        schedule = str(payload.get("schedule") or "").strip()
        next_run_at = next_cron_run(schedule)
        record = {
            "id": f"cron_{uuid.uuid4().hex[:12]}",
            "taskName": str(payload.get("taskName") or "").strip(),
            "schedule": schedule,
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
        return await self._repository.list_cron(str(user.tenant_id))

    async def delete_cron(self, cron_id: str, *, user: UserData) -> None:
        _require_identity(user)
        if not await self._repository.delete_cron(cron_id, str(user.tenant_id)):
            raise AutomationNotFoundError("Cron job not found")

    async def toggle_cron(self, cron_id: str, *, user: UserData) -> Dict[str, Any]:
        _require_identity(user)
        current = await self._repository.get_cron(cron_id, str(user.tenant_id))
        if current is None:
            raise AutomationNotFoundError("Cron job not found")
        next_run_at = next_cron_run(current["schedule"])
        updated = await self._repository.toggle_cron(
            cron_id,
            str(user.tenant_id),
            next_run_at=next_run_at,
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
