"""Thin HTTP ingress for durable automation jobs."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.job_service import (
    JobExecutionError,
    JobNotFoundError,
    JobService,
    LegacyAutomationMigrationRequired,
    get_job_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation/jobs", tags=["automation-jobs"])


class JobTask(BaseModel):
    name: str = Field(..., description="Name of the task")
    agent: str = Field(..., description="Agent assigned to the task")
    instructions: Optional[str] = Field(
        None, description="Specific instructions for this step"
    )


class JobDefinitionRequest(BaseModel):
    name: str = Field(..., description="Job name")
    description: str = Field(..., description="Description of the job")
    tasks: List[JobTask] = Field(
        default_factory=list, description="Chain of tasks"
    )
    trigger: str = Field("Manual Run", description="How this job is triggered")


class JobDefinitionResponse(JobDefinitionRequest):
    id: str
    created_at: datetime
    status: str = "Pending"


def _migration_required(exc: LegacyAutomationMigrationRequired) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.post("/", response_model=JobDefinitionResponse)
async def create_job(
    request: JobDefinitionRequest,
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    try:
        record = await job_service.create_job(request.dict(), user_context=user)
        return JobDefinitionResponse(**record)
    except LegacyAutomationMigrationRequired as exc:
        raise _migration_required(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "automation.jobs.create.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(status_code=500, detail="Failed to create job") from exc


@router.get("/", response_model=List[JobDefinitionResponse])
async def list_jobs(
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    try:
        records = await job_service.list_jobs(user)
        return [JobDefinitionResponse(**record) for record in records]
    except LegacyAutomationMigrationRequired as exc:
        raise _migration_required(exc) from exc
    except Exception as exc:
        logger.exception(
            "automation.jobs.list.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(status_code=500, detail="Failed to list jobs") from exc


@router.get("/{job_id}", response_model=JobDefinitionResponse)
async def get_job(
    job_id: str,
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    try:
        record = await job_service.get_job(job_id, user)
        if record is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobDefinitionResponse(**record)
    except LegacyAutomationMigrationRequired as exc:
        raise _migration_required(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "automation.jobs.get.failed",
            extra={
                "job_id": job_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to get job") from exc


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    try:
        if not await job_service.delete_job(job_id, user_context=user):
            raise HTTPException(status_code=404, detail="Job not found")
        return {"message": f"Job {job_id} deleted successfully"}
    except LegacyAutomationMigrationRequired as exc:
        raise _migration_required(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "automation.jobs.delete.failed",
            extra={
                "job_id": job_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to delete job") from exc


@router.post("/{job_id}/execute")
async def execute_job(
    job_id: str,
    user: UserData = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    try:
        return await job_service.execute_job(job_id, user_context=user)
    except LegacyAutomationMigrationRequired as exc:
        raise _migration_required(exc) from exc
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except JobExecutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "automation.jobs.execute.failed",
            extra={
                "job_id": job_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to execute job") from exc
