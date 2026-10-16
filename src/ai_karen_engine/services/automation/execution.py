"""Canonical execution adapters for durable automation definitions.

This service owns product-level task/job lifecycle transitions and scheduled
principal revalidation. It never selects providers or executes agents directly;
saved task content always reaches ChatRuntime through execute_task_definition.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.task_execution import execute_task_definition
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)
from ai_karen_engine.services.automation.claim_lease import (
    ClaimLeaseLost,
    run_with_claim_heartbeat,
)
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id


class AutomationExecutionError(RuntimeError):
    """Automation target reached runtime but did not complete successfully."""


class AutomationReviewConflict(AutomationExecutionError):
    """Review has already happened or the requested attempt is no longer current."""


class AutomationReviewForbidden(PermissionError):
    """Only the authenticated task creator can attest to completion."""


class AutomationTaskBusy(AutomationExecutionError):
    """A task already has a live owner or an unreconciled legacy owner."""


class AutomationTaskClaimLost(ClaimLeaseLost, AutomationExecutionError):
    """A stale or expired owner cannot publish the current task result."""


logger = logging.getLogger(__name__)


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


def _runtime_result_receipt(result: ChatExecutionResult) -> Dict[str, Any]:
    """Capture observable runtime output, never model claims of goal completion."""
    answer = result.answer or ""
    metadata = result.metadata
    max_chars = get_runtime_settings().task_verification.max_answer_chars
    if not 2400 <= max_chars <= 262144:
        raise AutomationExecutionError("Task verification answer limit is invalid")

    def _source_ref(value: Any) -> Dict[str, Optional[str]]:
        if not isinstance(value, dict):
            return {"title": None, "url": None}
        title = value.get("title") or value.get("name")
        title = title[:240] if isinstance(title, str) else None
        url = value.get("url")
        if isinstance(url, str):
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or len(url) > 1600
                or parsed.username
                or parsed.password
            ):
                url = None
        else:
            url = None
        return {"title": title, "url": url}

    def _ref(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        return value[:160] if value.strip() else None

    return {
        "runtime_status": result.status.value,
        "correlation_id": _ref(metadata.correlation_id),
        "response_id": _ref(metadata.response_id),
        "assistant_message_id": _ref(metadata.assistant_message_id),
        "conversation_id": _ref(metadata.conversation_id),
        "response_source": _ref(metadata.response_source),
        "actual_provider": _ref(metadata.actual_provider),
        "actual_model": _ref(metadata.actual_model),
        "degraded_mode": bool(metadata.degraded_mode),
        "answer_preview": answer[:2400],
        "answer_text": answer[:max_chars],
        "answer_truncated": len(answer) > max_chars,
        "artifact_count": len(result.artifacts),
        "attachment_count": len(result.attachments),
        "source_count": len(result.sources),
        "source_refs_truncated": len(result.sources) > 20,
        "sources": [_source_ref(item) for item in result.sources[:20]],
        "citation_count": len(result.citations),
        "independently_verified": False,
    }


async def review_saved_task(
    task_id: str,
    *,
    user: UserData,
    execution_id: str,
    decision: str,
    note: str = "",
    repository: Optional[SqlAutomationRepository] = None,
) -> Dict[str, Any]:
    """Human verification, guarded by current attempt identity and task owner."""
    tenant_id = str(user.tenant_id or "").strip()
    user_id = str(user.user_id or "").strip()
    if not tenant_id or tenant_id == "default" or not user_id:
        raise AutomationReviewForbidden("Authenticated identity is required")
    if decision not in {"approve", "reject"}:
        raise ValueError("Review decision must be approve or reject")
    if len(note) > 2000:
        raise ValueError("Review note is too long")
    try:
        normalized_attempt = str(uuid.UUID(execution_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Review execution_id must be a UUID") from exc
    repo = repository or get_automation_repository()
    task = await repo.get_task(task_id, tenant_id)
    if task is None:
        raise AutomationTargetNotFound("Task not found")
    if str(task.get("created_by") or "") != user_id:
        raise AutomationReviewForbidden("Only the task creator can review outcomes")
    if (
        task.get("status") != "ReviewRequired"
        or str(task.get("executionId") or "") != normalized_attempt
    ):
        raise AutomationReviewConflict("The selected task attempt is not reviewable")
    if decision == "approve":
        receipt = task.get("resultReceipt") or {}
        if (
            not receipt.get("answer_text")
            or receipt.get("answer_truncated") is not False
            or receipt.get("source_refs_truncated") is not False
            or int(receipt.get("artifact_count") or 0) > 0
            or int(receipt.get("attachment_count") or 0) > 0
            or len(receipt.get("sources") or []) != int(receipt.get("source_count") or 0)
        ):
            raise AutomationReviewConflict(
                "Complete reviewer-accessible output is required for approval"
            )
    reviewed = await repo.review_task(
        task_id, tenant_id, user_id=user_id, execution_id=normalized_attempt,
        decision=decision, note=note,
    )
    if reviewed is None:
        raise AutomationReviewConflict("The task attempt was already reviewed or replaced")
    logger.info(
        "automation.task.review_decided",
        extra={
            "task_id": task_id, "tenant_id": tenant_id, "user_id": user_id,
            "execution_id": normalized_attempt, "decision": decision,
            "status": reviewed["status"],
        },
    )
    return reviewed


async def execute_saved_task(
    task_id: str,
    *,
    user: UserData,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    repository: Optional[SqlAutomationRepository] = None,
) -> SavedTaskExecution:
    """Execute a saved task with one durable, tenant-scoped fenced owner."""
    repo = repository or get_automation_repository()
    tenant_id = str(user.tenant_id or "").strip()
    user_id = str(user.user_id or "").strip()
    if not tenant_id or tenant_id == "default" or not user_id:
        raise AutomationExecutionError("Authenticated tenant and user are required")

    settings = get_runtime_settings().timeouts
    lease_seconds = settings.saved_task_claim_lease_seconds
    heartbeat_seconds = settings.saved_task_claim_heartbeat_seconds
    if (
        lease_seconds < 30
        or heartbeat_seconds < 1
        or 2 * heartbeat_seconds >= lease_seconds
    ):
        raise AutomationExecutionError("Invalid saved task claim configuration")

    claim_token = str(uuid.uuid4())
    task = await repo.mark_task_running(
        task_id, tenant_id,
        claim_token=claim_token, lease_seconds=lease_seconds,
    )
    if task is None:
        if await repo.get_task(task_id, tenant_id) is None:
            raise AutomationTargetNotFound("Task not found")
        raise AutomationTaskBusy("Task has an active or unreconciled execution claim")

    resolved_request_id = request_id or f"task:{task_id}:{uuid.uuid4()}"
    resolved_correlation_id = correlation_id or resolved_request_id

    async def renew() -> bool:
        return await repo.renew_task_claim(
            task_id, tenant_id,
            claim_token=claim_token, lease_seconds=lease_seconds,
        )

    try:
        result = await run_with_claim_heartbeat(
            execute_task_definition(
                task,
                user=user,
                request_id=resolved_request_id,
                correlation_id=resolved_correlation_id,
            ),
            renew=renew,
            heartbeat_seconds=heartbeat_seconds,
            lost_error=AutomationTaskClaimLost,
            lost_message="Saved task execution lost its durable ownership",
        )
    except asyncio.CancelledError:
        try:
            await repo.complete_task(
                task_id, tenant_id, claim_token=claim_token,
                status="Failed", last_error="Task execution cancelled",
            )
        except Exception:
            logger.exception(
                "automation.task.cancel_finalization_failed",
                extra={"task_id": task_id, "tenant_id": tenant_id,
                       "correlation_id": resolved_correlation_id},
            )
        raise
    except AutomationTaskClaimLost:
        # Never let an expired owner update the latest task state.
        raise
    except Exception as exc:
        failed = await repo.complete_task(
            task_id, tenant_id, claim_token=claim_token,
            status="Failed", last_error=type(exc).__name__,
        )
        if failed is None:
            raise AutomationTaskClaimLost(
                "Task failed after its execution claim was lost"
            ) from exc
        raise

    successful = (
        result.status in {ChatExecutionStatus.OK, ChatExecutionStatus.DEGRADED}
        and bool(result.answer.strip())
    )
    completed = await repo.complete_task(
        task_id, tenant_id,
        claim_token=claim_token,
        status="ReviewRequired" if successful else "Failed",
        last_error=(
            None if successful else
            "runtime_gate" if result.status == ChatExecutionStatus.GATE
            else "runtime_execution_failed"
        ),
        runtime_task_id=result.metadata.correlation_id,
        result_receipt=_runtime_result_receipt(result),
    )
    if completed is None:
        raise AutomationTaskClaimLost(
            "Task result rejected because its execution claim expired or changed"
        )
    if not successful:
        raise AutomationExecutionError("Task execution was not completed")
    logger.info(
        "automation.task.execution_completed",
        extra={
            "task_id": task_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "correlation_id": resolved_correlation_id,
            "request_id": resolved_request_id,
            "runtime_task_id": result.metadata.correlation_id,
            "status": completed["status"],
        },
    )
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
            "status": outcome.task["status"],
            "execution_id": outcome.task.get("executionId"),
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
    "AutomationTaskBusy",
    "AutomationReviewConflict",
    "AutomationReviewForbidden",
    "review_saved_task",
    "AutomationTaskClaimLost",
    "SavedTaskExecution",
    "execute_automation_target",
    "execute_saved_task",
    "resolve_scheduled_principal",
]
