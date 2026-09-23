"""Thin HTTP ingress for durable saved task definitions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

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
    AutomationTargetNotFound,
    execute_saved_task,
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


class TaskDefinitionResponse(TaskDefinitionRequest):
    id: str
    lastRun: Optional[str] = None
    status: str = "Pending"
    created_at: datetime
    updated_at: datetime
    lastError: Optional[str] = None
    runCount: int = 0
    runtimeTaskId: Optional[str] = None


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
        "message": f"Task {task_id} executed successfully",
        "task_id": task_id,
        "runtime_task_id": outcome.result.metadata.correlation_id,
        "status": outcome.task["status"],
        "agent_id": outcome.task.get("primaryAgent"),
        "response": outcome.result.answer,
        "runtime_metadata": outcome.result.metadata.to_dict(),
    }
