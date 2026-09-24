"""Canonical execution adapters for durable automation definitions.

This service owns product-level task/job lifecycle transitions and scheduled
principal revalidation. It never selects providers or executes agents directly;
saved task content always reaches ChatRuntime through execute_task_definition.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.task_execution import execute_task_definition
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id


class AutomationExecutionError(RuntimeError):
    """Automation target reached runtime but did not complete successfully."""


class AutomationTargetNotFound(LookupError):
    """Automation target does not exist in the tenant."""


class AutomationPrincipalUnavailable(PermissionError):
    """Saved schedule owner is no longer an authorized active principal."""


@dataclass(frozen=True)
class SavedTaskExecution:
    task: Dict[str, Any]
    result: ChatExecutionResult


def _role_values(roles: Any) -> list[str]:
    return [str(getattr(role, "value", role)) for role in (roles or [])]


async def resolve_scheduled_principal(
    *,
    user_id: str,
    tenant_id: str,
) -> UserData:
    """Revalidate the durable schedule owner against fresh database-backed auth state."""
    auth = await get_auth_service()
    account = await get_fresh_user_by_id(
        auth,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    if account is None:
        raise AutomationPrincipalUnavailable("Schedule owner no longer exists in tenant")
    if account.status != UserStatus.ACTIVE:
        raise AutomationPrincipalUnavailable("Schedule owner is not active")
    if str(account.tenant_id or "") != str(tenant_id):
        raise AutomationPrincipalUnavailable("Schedule owner tenant changed")
    return UserData(
        user_id=account.id,
        email=account.email,
        username=account.username,
        roles=_role_values(account.roles),
        tenant_id=account.tenant_id,
        full_name=account.full_name,
        preferences=dict(account.preferences or {}),
        is_active=True,
        is_verified=bool(account.is_verified),
    )


async def execute_saved_task(
    task_id: str,
    *,
    user: UserData,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    repository: Optional[SqlAutomationRepository] = None,
) -> SavedTaskExecution:
    """Run a durable saved task and persist its terminal lifecycle."""
    repo = repository or get_automation_repository()
    tenant_id = str(user.tenant_id or "").strip()
    if not tenant_id:
        raise AutomationExecutionError("Explicit tenant_id is required")

    task = await repo.mark_task_running(task_id, tenant_id)
    if task is None:
        raise AutomationTargetNotFound("Task not found")

    resolved_request_id = request_id or f"task:{task_id}:{uuid.uuid4()}"
    resolved_correlation_id = correlation_id or resolved_request_id
    try:
        result = await execute_task_definition(
            task,
            user=user,
            request_id=resolved_request_id,
            correlation_id=resolved_correlation_id,
        )
    except asyncio.CancelledError:
        await repo.complete_task(
            task_id,
            tenant_id,
            status="Failed",
            last_error="Task execution cancelled",
        )
        raise
    except Exception as exc:
        await repo.complete_task(
            task_id,
            tenant_id,
            status="Failed",
            last_error=type(exc).__name__,
        )
        raise

    successful = result.status in {
        ChatExecutionStatus.OK,
        ChatExecutionStatus.DEGRADED,
    } and bool(result.answer)
    runtime_task_id = result.metadata.correlation_id
    completed = await repo.complete_task(
        task_id,
        tenant_id,
        status="Success" if successful else "Failed",
        last_error=(
            None
            if successful
            else (
                "runtime_gate"
                if result.status == ChatExecutionStatus.GATE
                else "runtime_execution_failed"
            )
        ),
        runtime_task_id=runtime_task_id,
    )
    if completed is None:
        raise AutomationExecutionError("Task lifecycle update failed")
    if not successful:
        raise AutomationExecutionError("Task execution was not completed")
    return SavedTaskExecution(task=completed, result=result)


async def execute_automation_target(
    *,
    job_type: str,
    target_id: str,
    user: UserData,
    source_id: str,
) -> Dict[str, Any]:
    """Execute one durable task or job through its canonical authority."""
    correlation_id = f"automation:{source_id}:{uuid.uuid4()}"
    if job_type == "Task":
        outcome = await execute_saved_task(
            target_id,
            user=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
        )
        return {
            "target_type": "Task",
            "target_id": target_id,
            "runtime_task_id": outcome.result.metadata.correlation_id,
            "status": "Success",
        }

    if job_type in {"Job", "Sequence"}:
        from ai_karen_engine.services.job_service import get_job_service

        result = await get_job_service().execute_job(target_id, user_context=user)
        return {
            "target_type": "Job",
            "target_id": target_id,
            "status": result["status"],
        }

    raise AutomationExecutionError(f"Unsupported automation target type: {job_type}")


__all__ = [
    "AutomationExecutionError",
    "AutomationPrincipalUnavailable",
    "AutomationTargetNotFound",
    "SavedTaskExecution",
    "execute_automation_target",
    "execute_saved_task",
    "resolve_scheduled_principal",
]
