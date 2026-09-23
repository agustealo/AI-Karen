"""Durable multi-step automation job service.

Job definitions live in PostgreSQL and every AI-bearing step delegates to the
canonical ChatRuntime task adapter. No file-backed registry, direct AgentTask
execution, or detached background coroutine exists here.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionStatus
from ai_karen_engine.core.runtime.task_execution import execute_task_definition
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)


class JobNotFoundError(LookupError):
    """Tenant-scoped job definition does not exist."""


class JobExecutionError(RuntimeError):
    """Job execution failed."""


class JobService:
    """Canonical product-level owner for durable multi-step automation jobs."""

    def __init__(self, repository: Optional[SqlAutomationRepository] = None) -> None:
        self._repository = repository or get_automation_repository()

    @staticmethod
    def _user(user_context: Any) -> UserData:
        user = UserData.ensure(user_context)
        if not str(user.user_id or "").strip():
            raise ValueError("Authenticated user_id is required")
        if not str(user.tenant_id or "").strip() or str(user.tenant_id) == "default":
            raise ValueError("Explicit tenant_id is required")
        return user

    async def list_jobs(self, user_context: Any) -> List[Dict[str, Any]]:
        user = self._user(user_context)
        return await self._repository.list_jobs(str(user.tenant_id))

    async def get_job(
        self, job_id: str, user_context: Any
    ) -> Optional[Dict[str, Any]]:
        user = self._user(user_context)
        return await self._repository.get_job(job_id, str(user.tenant_id))

    async def create_job(
        self,
        job_data: Dict[str, Any],
        *,
        user_context: Any,
    ) -> Dict[str, Any]:
        user = self._user(user_context)
        name = str(job_data.get("name") or "").strip()
        description = str(job_data.get("description") or "").strip()
        if not name or not description:
            raise ValueError("Job name and description are required")
        record = {
            "id": f"job_{uuid.uuid4().hex[:12]}",
            "name": name,
            "description": description,
            "tasks": list(job_data.get("tasks") or []),
            "trigger": str(job_data.get("trigger") or "Manual Run"),
        }
        return await self._repository.create_job(
            tenant_id=str(user.tenant_id),
            created_by=str(user.user_id),
            record=record,
        )

    async def delete_job(self, job_id: str, *, user_context: Any) -> bool:
        user = self._user(user_context)
        return await self._repository.delete_job(job_id, str(user.tenant_id))

    async def execute_job(
        self,
        job_id: str,
        user_context: Any,
    ) -> Dict[str, Any]:
        """Execute job steps serially through ChatRuntime and persist the outcome."""
        user = self._user(user_context)
        tenant_id = str(user.tenant_id)
        job = await self._repository.mark_job_running(job_id, tenant_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} not found")

        results: List[Dict[str, Any]] = []
        try:
            for index, step in enumerate(job.get("tasks") or []):
                step_name = str(step.get("name") or f"Step {index + 1}")
                agent = str(step.get("agent") or "").strip()
                if not agent:
                    raise JobExecutionError(
                        f"Job {job_id} step {index + 1} has no assigned agent"
                    )
                inline_task = {
                    "id": f"{job_id}:step:{index}",
                    "name": step_name,
                    "description": str(step.get("instructions") or step_name),
                    "primaryAgent": agent,
                    "primaryAgentInstructions": str(step.get("instructions") or ""),
                    "taskType": "automation_step",
                    "subAgents": [],
                    "tenant_id": tenant_id,
                    "created_by": str(user.user_id),
                }
                correlation_id = (
                    f"job:{job_id}:step:{index}:{uuid.uuid4()}"
                )
                runtime_result = await execute_task_definition(
                    inline_task,
                    user=user,
                    request_id=correlation_id,
                    correlation_id=correlation_id,
                )
                success = runtime_result.status in {
                    ChatExecutionStatus.OK,
                    ChatExecutionStatus.DEGRADED,
                } and bool(runtime_result.answer)
                results.append(
                    {
                        "step": step_name,
                        "success": success,
                        "runtime_task_id": runtime_result.metadata.correlation_id,
                        "status": runtime_result.status.value,
                        "response": runtime_result.answer if success else None,
                    }
                )
                if not success:
                    raise JobExecutionError(
                        f"Job {job_id} step {index + 1} did not complete"
                    )
        except asyncio.CancelledError:
            await self._repository.complete_job(
                job_id,
                tenant_id,
                status="Failed",
                results=results,
                last_error="Job execution cancelled",
            )
            raise
        except Exception as exc:
            await self._repository.complete_job(
                job_id,
                tenant_id,
                status="Failed",
                results=results,
                last_error=type(exc).__name__,
            )
            raise

        completed = await self._repository.complete_job(
            job_id,
            tenant_id,
            status="Success",
            results=results,
            last_error=None,
        )
        if completed is None:
            raise JobExecutionError("Job lifecycle update failed")
        return {
            "message": f"Job {job_id} executed successfully",
            "job_id": job_id,
            "status": "Success",
            "results": results,
        }


_job_service: Optional[JobService] = None


def get_job_service() -> JobService:
    global _job_service
    if _job_service is None:
        _job_service = JobService()
    return _job_service


__all__ = [
    "JobExecutionError",
    "JobNotFoundError",
    "JobService",
    "get_job_service",
]
