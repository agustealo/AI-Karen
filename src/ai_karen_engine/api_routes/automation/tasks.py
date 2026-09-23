"""API routes for saved task definitions.

Routes own authenticated HTTP ingress only. AI execution is delegated to the
canonical ChatRuntime through the runtime-owned task-definition adapter.
"""

from __future__ import annotations

from datetime import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ai_karen_engine.agents import get_agent_integration_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionStatus
from ai_karen_engine.core.runtime.task_execution import execute_task_definition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class SubAgentConfig(BaseModel):
    name: str = Field(..., description="Name of the sub-agent assigned")
    instructions: str = Field(..., description="Specific instructions for this sub-agent")
    agentId: Optional[str] = Field(
        None, description="Optional live agent identifier for the sub-agent"
    )


class TaskDefinitionRequest(BaseModel):
    name: str = Field(..., description="Task name")
    description: str = Field(..., description="Detailed description of what the task does")
    primaryAgent: str = Field(..., description="Primary agent responsible for the outcome")
    primaryAgentInstructions: str = Field("", description="Instructions for the primary agent")
    taskType: Optional[str] = Field(
        None, description="Optional runtime task type used for execution routing"
    )
    subAgents: List[SubAgentConfig] = Field(
        default_factory=list,
        description="Delegated sub-agents and instructions",
    )


class TaskDefinitionResponse(TaskDefinitionRequest):
    id: str = Field(..., description="Unique task identifier")
    lastRun: Optional[str] = Field(None, description="When the task was last executed")
    status: str = Field(
        "Pending",
        description="Status of the task (e.g., Success, Failed, Pending, Running)",
    )
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Task update timestamp")
    lastError: Optional[str] = Field(None, description="Last execution error, if any")
    runCount: int = Field(0, description="Number of executions for this task")
    runtimeTaskId: Optional[str] = Field(
        None, description="Last canonical runtime correlation identifier"
    )


# Transitional definition registry. Execution no longer uses the legacy agent
# integration executor. This registry remains intentionally isolated so the
# next persistence slice can replace it without changing the HTTP contract.
_tasks_db: Dict[str, Dict[str, Any]] = {}


def _slugify_task_type(name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "general_task"


def _normalize_task_record(task_record: Dict[str, Any]) -> TaskDefinitionResponse:
    record = dict(task_record)
    record.setdefault("updated_at", record.get("created_at", datetime.utcnow()))
    record.setdefault("lastError", None)
    record.setdefault("runCount", 0)
    record.setdefault("runtimeTaskId", None)
    record.setdefault(
        "taskType",
        record.get("taskType") or _slugify_task_type(record["name"]),
    )
    return TaskDefinitionResponse(**record)


def _task_for_user(task_id: str, user: UserData) -> Dict[str, Any]:
    """Return a task only when it belongs to the authenticated tenant."""
    task = _tasks_db.get(task_id)
    if task is None or str(task.get("tenant_id") or "") != str(user.tenant_id):
        # Hide cross-tenant existence rather than exposing an authorization oracle.
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def get_tasks_summary(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Return task statistics, optionally restricted to one tenant."""
    tasks = list(_tasks_db.values())
    if tenant_id is not None:
        tasks = [t for t in tasks if str(t.get("tenant_id") or "") == tenant_id]

    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    tasks_today = 0
    for task in tasks:
        updated_at = task.get("updated_at")
        if isinstance(updated_at, datetime) and updated_at >= today_start:
            tasks_today += int(task.get("runCount", 0))

    return {
        "total_definitions": len(tasks),
        "tasks_run_today": tasks_today,
        "active_tasks": len([t for t in tasks if t.get("status") == "Running"]),
        "failed_tasks": len([t for t in tasks if t.get("status") == "Failed"]),
    }


@router.post("/", response_model=TaskDefinitionResponse)
async def create_task(
    request: TaskDefinitionRequest,
    user: UserData = Depends(get_current_user),
):
    """Create a task definition in the authenticated tenant."""
    try:
        # Agent existence validation is compatibility-only. It does not execute
        # the task or choose an AI runtime/provider.
        integration_service = get_agent_integration_service()
        await integration_service.initialize()

        primary_agent = await integration_service.get_agent_info(request.primaryAgent)
        if not primary_agent:
            raise HTTPException(
                status_code=404,
                detail=f"Primary agent {request.primaryAgent} not found",
            )

        for sub_agent in request.subAgents:
            if sub_agent.agentId:
                sub_agent_info = await integration_service.get_agent_info(sub_agent.agentId)
                if not sub_agent_info:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Sub-agent {sub_agent.agentId} not found",
                    )

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()
        task_record = {
            "id": task_id,
            "name": request.name,
            "description": request.description,
            "primaryAgent": request.primaryAgent,
            "primaryAgentInstructions": request.primaryAgentInstructions,
            "taskType": request.taskType or _slugify_task_type(request.name),
            "subAgents": [sa.dict() for sa in request.subAgents],
            "lastRun": None,
            "status": "Pending",
            "created_at": now,
            "updated_at": now,
            "lastError": None,
            "runCount": 0,
            "runtimeTaskId": None,
            "created_by": user.user_id,
            "tenant_id": user.tenant_id,
        }
        _tasks_db[task_id] = task_record
        return _normalize_task_record(task_record)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "tasks.create.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(status_code=500, detail="Failed to create task") from exc


@router.get("/", response_model=List[TaskDefinitionResponse])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by task status"),
    agent_name: Optional[str] = Query(None, description="Filter by primary agent name"),
    user: UserData = Depends(get_current_user),
):
    """List task definitions in the authenticated tenant only."""
    tasks = [
        task
        for task in _tasks_db.values()
        if str(task.get("tenant_id") or "") == str(user.tenant_id)
    ]
    if status:
        tasks = [task for task in tasks if task["status"] == status]
    if agent_name:
        tasks = [task for task in tasks if task["primaryAgent"] == agent_name]
    tasks.sort(key=lambda item: item["created_at"], reverse=True)
    return [_normalize_task_record(task) for task in tasks]


@router.get("/{task_id}", response_model=TaskDefinitionResponse)
async def get_task(
    task_id: str,
    user: UserData = Depends(get_current_user),
):
    """Get one task definition from the authenticated tenant."""
    return _normalize_task_record(_task_for_user(task_id, user))


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: UserData = Depends(get_current_user),
):
    """Delete a task definition from the authenticated tenant."""
    _task_for_user(task_id, user)
    del _tasks_db[task_id]
    return {"message": f"Task {task_id} deleted successfully"}


@router.post("/{task_id}/execute")
async def execute_task(
    task_id: str,
    user: UserData = Depends(get_current_user),
):
    """Execute a task through canonical ChatRuntime authority."""
    task = _task_for_user(task_id, user)
    now = datetime.utcnow()
    task["status"] = "Running"
    task["lastRun"] = now.strftime("%Y-%m-%d %H:%M UTC")
    task["updated_at"] = now
    task["lastError"] = None
    task["runCount"] = int(task.get("runCount", 0)) + 1

    try:
        execution = await execute_task_definition(task, user=user)
    except Exception as exc:
        task["status"] = "Failed"
        task["updated_at"] = datetime.utcnow()
        task["lastError"] = type(exc).__name__
        logger.exception(
            "tasks.execute.failed",
            extra={
                "task_id": task_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Task execution failed") from exc

    correlation_id = execution.metadata.correlation_id
    task["runtimeTaskId"] = correlation_id
    task["updated_at"] = datetime.utcnow()

    successful = execution.status in {
        ChatExecutionStatus.OK,
        ChatExecutionStatus.DEGRADED,
    } and bool(execution.answer)
    if successful:
        task["status"] = "Success"
        task["lastError"] = None
    else:
        task["status"] = "Failed"
        task["lastError"] = (
            "runtime_gate"
            if execution.status == ChatExecutionStatus.GATE
            else "runtime_execution_failed"
        )

    if not successful:
        raise HTTPException(status_code=503, detail="Task execution was not completed")

    return {
        "message": f"Task {task_id} executed successfully",
        "task_id": task_id,
        "runtime_task_id": correlation_id,
        "status": task["status"],
        "agent_id": task.get("primaryAgent"),
        "response": execution.answer,
        "runtime_metadata": execution.metadata.to_dict(),
    }
