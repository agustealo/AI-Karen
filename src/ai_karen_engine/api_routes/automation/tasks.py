"""Thin HTTP ingress for durable saved task definitions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.middleware.correlation_middleware import get_request_correlation_id
from ai_karen_engine.services.automation.definitions import (
    AutomationDefinitionError,
    AutomationNotFoundError,
    get_automation_definition_service,
)
from ai_karen_engine.services.automation.execution import (
    AutomationExecutionError,
    AutomationTaskBusy,
    AutomationTaskClaimLost,
    AutomationTargetNotFound,
    AutomationReviewConflict,
    AutomationReviewForbidden,
    execute_saved_task,
    review_saved_task,
    list_saved_task_reviews,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class SubAgentConfig(BaseModel):
    name: str = Field(..., description="Name of the sub-agent assigned")
    instructions: str = Field(
        ..., description="Specific instructions for this sub-agent"
    )
    agentId: Optional[str] = Field(
        None, description="Optional live agent identifier for the sub-agent"
    )


class TaskDefinitionRequest(BaseModel):
    name: str = Field(..., description="Task name")
    description: str = Field(
        ..., description="Detailed description of what the task does"
    )
    acceptanceCriteria: str = Field(
        "", max_length=4000,
        description="User-defined acceptance criteria for the human completion review",
    )
    primaryAgent: str = Field(
        ..., description="Primary agent responsible for the outcome"
    )
    primaryAgentInstructions: str = Field(
        "", description="Instructions for the primary agent"
    )
    taskType: Optional[str] = Field(
        None, description="Optional runtime task type used for execution routing"
    )
    subAgents: List[SubAgentConfig] = Field(
        default_factory=list,
        description="Delegated sub-agents and instructions",
    )


class TaskReviewRequest(BaseModel):
    execution_id: str = Field(..., min_length=36, max_length=36)
    decision: Literal["approve", "reject"]
    note: str = Field("", max_length=2000)


class TaskReviewHistoryResponse(BaseModel):
    outcome_id: str
    execution_id: str
    decision: Literal["approve", "reject"]
    status: str
    review_note: str
    reviewed_at: datetime
    acceptance_criteria: str
    receipt_sha256: str
    result_receipt: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    human_attestation: bool
    independently_verified: bool


class TaskDefinitionResponse(TaskDefinitionRequest):
    id: str
    lastRun: Optional[str] = None
    status: str = "Pending"
    created_at: datetime
    updated_at: datetime
    lastError: Optional[str] = None
    runCount: int = 0
    runtimeTaskId: Optional[str] = None
    executionId: Optional[str] = None
    resultReceipt: Dict[str, Any] = Field(default_factory=dict)
    reviewedAt: Optional[str] = None
    reviewedBy: Optional[str] = None
    reviewNote: Optional[str] = None


async def get_tasks_summary(tenant_id: str) -> dict:
    """Tenant-scoped task statistics for the automation dashboard."""
    return await get_automation_definition_service().task_summary(
        tenant_id=tenant_id
    )


@router.post("/", response_model=TaskDefinitionResponse)
async def create_task(
    request: TaskDefinitionRequest,
    user: UserData = Depends(get_current_user),
):
    try:
        record = await get_automation_definition_service().create_task(
            request.dict(),
            user=user,
        )
        return TaskDefinitionResponse(**record)
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AutomationDefinitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "tasks.create.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(status_code=500, detail="Failed to create task") from exc


@router.get("/", response_model=List[TaskDefinitionResponse])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by task status"),
    agent_name: Optional[str] = Query(
        None, description="Filter by primary agent name"
    ),
    user: UserData = Depends(get_current_user),
):
    try:
        records = await get_automation_definition_service().list_tasks(
            user=user,
            status=status,
            agent_name=agent_name,
        )
        return [TaskDefinitionResponse(**record) for record in records]
    except AutomationDefinitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}", response_model=TaskDefinitionResponse)
async def get_task(
    task_id: str,
    user: UserData = Depends(get_current_user),
):
    try:
        record = await get_automation_definition_service().get_task(
            task_id, user=user
        )
        return TaskDefinitionResponse(**record)
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: UserData = Depends(get_current_user),
):
    try:
        await get_automation_definition_service().delete_task(task_id, user=user)
        return {"message": f"Task {task_id} deleted successfully"}
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@router.get("/{task_id}/reviews", response_model=List[TaskReviewHistoryResponse])
async def get_task_reviews(
    task_id: str,
    limit: int = Query(50, ge=1, le=100),
    user: UserData = Depends(get_current_user),
):
    try:
        records = await list_saved_task_reviews(
            task_id, user=user, limit=limit,
        )
        return [TaskReviewHistoryResponse(**record) for record in records]
    except AutomationTargetNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except AutomationReviewForbidden as exc:
        raise HTTPException(status_code=403, detail="Task history denied") from exc
    except OutcomeStoreError as exc:
        raise HTTPException(
            status_code=503, detail="Task review history unavailable",
        ) from exc


@router.post("/{task_id}/review", response_model=TaskDefinitionResponse)
async def review_task(
    task_id: str,
    body: TaskReviewRequest,
    user: UserData = Depends(get_current_user),
):
    try:
        return TaskDefinitionResponse(
            **await review_saved_task(
                task_id,
                user=user,
                execution_id=body.execution_id,
                decision=body.decision,
                note=body.note,
            )
        )
    except AutomationTargetNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except AutomationReviewForbidden as exc:
        raise HTTPException(status_code=403, detail="Task review denied") from exc
    except AutomationReviewConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Task attempt was already reviewed or replaced",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/execute")
async def execute_task(
    task_id: str,
    request: Request,
    user: UserData = Depends(get_current_user),
):
    correlation_id = get_request_correlation_id(request)
    request_id = str(getattr(request.state, "request_id", correlation_id))
    try:
        outcome = await execute_saved_task(
            task_id,
            user=user,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except asyncio.CancelledError:
        logger.warning(
            "tasks.execute.cancelled",
            extra={
                "task_id": task_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise
    except AutomationTargetNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except AutomationTaskBusy as exc:
        raise HTTPException(
            status_code=409,
            detail="Task already has a running or unreconciled execution",
        ) from exc
    except AutomationTaskClaimLost as exc:
        raise HTTPException(
            status_code=409,
            detail="Task execution ownership expired; result was not committed",
        ) from exc
    except AutomationExecutionError as exc:
        raise HTTPException(
            status_code=503, detail="Task execution was not completed"
        ) from exc
    except Exception as exc:
        logger.exception(
            "tasks.execute.failed",
            extra={
                "task_id": task_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Task execution failed") from exc

    return {
        "message": "Task execution finished; human completion review required",
        "task_id": task_id,
        "runtime_task_id": outcome.result.metadata.correlation_id,
        "status": outcome.task["status"],
        "execution_id": outcome.task.get("executionId"),
        "result_receipt": outcome.task.get("resultReceipt", {}),
        "agent_id": outcome.task.get("primaryAgent"),
        "response": outcome.result.answer,
        "runtime_metadata": outcome.result.metadata.to_dict(),
    }
