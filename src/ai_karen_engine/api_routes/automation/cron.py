"""Thin API ingress plus durable scheduler workers for automation cron jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.persistence.repositories.automation_repository import (
    get_automation_repository,
)
from ai_karen_engine.services.automation.definitions import (
    AutomationDefinitionError,
    AutomationNotFoundError,
    get_automation_definition_service,
    next_cron_run,
)
from ai_karen_engine.services.automation.execution import (
    execute_automation_target,
    resolve_scheduled_principal,
)
from ai_karen_engine.services.database.repositories.queue_accessor import (
    enqueue,
    get_queue_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation/cron", tags=["automation-cron"])

_AUTOMATION_QUEUE = "automation"
_CRON_POLL_SECONDS = 10
_QUEUE_POLL_SECONDS = 5

_cron_executor_task: Optional[asyncio.Task] = None
_queue_worker_task: Optional[asyncio.Task] = None


class CronJobRequest(BaseModel):
    taskName: str = Field(..., description="Task or Sequence Name")
    schedule: str = Field(..., description="Cron expression")
    type: str = Field(..., description="'Task', 'Job', or 'Sequence'")
    targetId: str = Field(
        ..., description="The ID of the Task or Job to trigger"
    )
    enabled: bool = Field(True, description="Whether this cron job is active")
    action: str = Field("execute", description="'execute' or 'enqueue'")


class CronJobResponse(CronJobRequest):
    id: str
    nextRun: str
    created_at: datetime


async def get_cron_summary(tenant_id: str) -> Dict[str, Any]:
    """Tenant-scoped cron statistics for the automation dashboard."""
    return await get_automation_definition_service().cron_summary(
        tenant_id=tenant_id
    )


@router.post("", response_model=CronJobResponse)
async def create_cron_job(
    request: CronJobRequest,
    user: UserData = Depends(get_current_user),
):
    try:
        record = await get_automation_definition_service().create_cron(
            request.dict(),
            user=user,
        )
        return CronJobResponse(**record)
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AutomationDefinitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "automation.cron.create.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(
            status_code=500, detail="Failed to create cron job"
        ) from exc


@router.get("", response_model=List[CronJobResponse])
async def list_cron_jobs(
    user: UserData = Depends(get_current_user),
):
    try:
        records = await get_automation_definition_service().list_cron(user=user)
        return [CronJobResponse(**record) for record in records]
    except Exception as exc:
        logger.exception(
            "automation.cron.list.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(
            status_code=500, detail="Failed to list cron jobs"
        ) from exc


@router.delete("/{cron_id}")
async def delete_cron_job(
    cron_id: str,
    user: UserData = Depends(get_current_user),
):
    try:
        await get_automation_definition_service().delete_cron(
            cron_id, user=user
        )
        return {"message": f"Cron job {cron_id} deleted successfully"}
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Cron job not found") from exc


@router.put("/{cron_id}/toggle", response_model=CronJobResponse)
async def toggle_cron_job(
    cron_id: str,
    user: UserData = Depends(get_current_user),
):
    try:
        record = await get_automation_definition_service().toggle_cron(
            cron_id, user=user
        )
        return CronJobResponse(**record)
    except AutomationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Cron job not found") from exc


async def _dispatch_claimed_cron(job: Dict[str, Any]) -> Optional[str]:
    """Execute or durably enqueue one claimed cron occurrence."""
    tenant_id = str(job["tenant_id"])
    created_by = str(job["created_by"])
    cron_id = str(job["id"])
    job_type = str(job["type"])
    target_id = str(job["targetId"])

    if job["action"] == "enqueue":
        item_id = await enqueue(
            _AUTOMATION_QUEUE,
            {
                "cron_id": cron_id,
                "target_id": target_id,
                "job_type": job_type,
                "tenant_id": tenant_id,
                "created_by": created_by,
                "trigger": "cron",
            },
            tenant_id=tenant_id,
        )
        if not item_id:
            raise RuntimeError("Durable queue enqueue failed")
        logger.info(
            "automation.cron.enqueued",
            extra={
                "cron_id": cron_id,
                "queue_item_id": item_id,
                "tenant_id": tenant_id,
            },
        )
        return item_id

    principal = await resolve_scheduled_principal(
        user_id=created_by,
        tenant_id=tenant_id,
    )
    await execute_automation_target(
        job_type=job_type,
        target_id=target_id,
        user=principal,
        source_id=cron_id,
    )
    return None


async def _cron_executor_loop() -> None:
    """Claim due schedules with leases and dispatch them without duplicate scans."""
    worker_id = f"cron-scheduler-{uuid.uuid4().hex[:12]}"
    repository = get_automation_repository()
    logger.info(
        "automation.cron.worker.started",
        extra={"worker_id": worker_id},
    )
    while True:
        try:
            claimed = await repository.claim_due_cron_jobs(worker_id)
            if not claimed:
                await asyncio.sleep(_CRON_POLL_SECONDS)
                continue

            for job in claimed:
                claim_token = str(job.get("claim_token") or "")
                error: Optional[str] = None
                try:
                    await _dispatch_claimed_cron(job)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:4000]
                    logger.exception(
                        "automation.cron.dispatch.failed",
                        extra={
                            "cron_id": job["id"],
                            "tenant_id": job["tenant_id"],
                            "worker_id": worker_id,
                        },
                    )
                finally:
                    next_run_at = next_cron_run(
                        str(job["schedule"]),
                        now=datetime.now(timezone.utc),
                    )
                    completed = await repository.complete_cron_claim(
                        str(job["id"]),
                        claim_token,
                        next_run_at=next_run_at,
                        last_error=error,
                    )
                    if not completed:
                        logger.error(
                            "automation.cron.claim_completion_failed",
                            extra={
                                "cron_id": job["id"],
                                "claim_token": claim_token,
                                "worker_id": worker_id,
                            },
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "automation.cron.worker.failed",
                extra={"worker_id": worker_id},
            )
            await asyncio.sleep(_CRON_POLL_SECONDS)


async def _queue_worker_loop() -> None:
    """Process the one canonical durable automation queue."""
    worker_id = f"automation-worker-{uuid.uuid4().hex[:12]}"
    client = get_queue_client()
    logger.info(
        "automation.queue.worker.started",
        extra={"worker_id": worker_id, "queue": _AUTOMATION_QUEUE},
    )
    while True:
        try:
            result = await client.dequeue(_AUTOMATION_QUEUE, worker_id)
            if not result.success:
                logger.error(
                    "automation.queue.dequeue.failed",
                    extra={
                        "worker_id": worker_id,
                        "error": result.error,
                    },
                )
                await asyncio.sleep(_QUEUE_POLL_SECONDS)
                continue
            item = result.data
            if item is None:
                await asyncio.sleep(_QUEUE_POLL_SECONDS)
                continue

            payload = dict(item.payload or {})
            try:
                tenant_id = str(payload["tenant_id"])
                created_by = str(payload["created_by"])
                if item.tenant_id and str(item.tenant_id) != tenant_id:
                    raise RuntimeError("Queue tenant metadata mismatch")

                principal = await resolve_scheduled_principal(
                    user_id=created_by,
                    tenant_id=tenant_id,
                )
                await execute_automation_target(
                    job_type=str(payload["job_type"]),
                    target_id=str(payload["target_id"]),
                    user=principal,
                    source_id=str(payload.get("cron_id") or item.id),
                )
                ack = await client.ack(
                    item.queue,
                    item.id,
                    claim_token=item.claim_token,
                )
                if not ack.success or not ack.data:
                    raise RuntimeError(
                        ack.error or "Queue acknowledgement claim was lost"
                    )
                logger.info(
                    "automation.queue.completed",
                    extra={
                        "queue_item_id": item.id,
                        "tenant_id": tenant_id,
                        "worker_id": worker_id,
                    },
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                nack = await client.nack(
                    item.queue,
                    item.id,
                    str(exc),
                    claim_token=item.claim_token,
                )
                logger.exception(
                    "automation.queue.processing.failed",
                    extra={
                        "queue_item_id": item.id,
                        "worker_id": worker_id,
                        "nack_success": bool(nack.success and nack.data),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "automation.queue.worker.failed",
                extra={"worker_id": worker_id},
            )
            await asyncio.sleep(_QUEUE_POLL_SECONDS)


@router.on_event("startup")
async def _start_cron_executor() -> None:
    global _cron_executor_task
    if _cron_executor_task and not _cron_executor_task.done():
        return
    _cron_executor_task = asyncio.create_task(_cron_executor_loop())


@router.on_event("shutdown")
async def _stop_cron_executor() -> None:
    global _cron_executor_task
    if not _cron_executor_task:
        return
    _cron_executor_task.cancel()
    try:
        await _cron_executor_task
    except asyncio.CancelledError:
        pass
    finally:
        _cron_executor_task = None


@router.on_event("startup")
async def _start_queue_worker() -> None:
    global _queue_worker_task
    if _queue_worker_task and not _queue_worker_task.done():
        return
    _queue_worker_task = asyncio.create_task(_queue_worker_loop())


@router.on_event("shutdown")
async def _stop_queue_worker() -> None:
    global _queue_worker_task
    if not _queue_worker_task:
        return
    _queue_worker_task.cancel()
    try:
        await _queue_worker_task
    except asyncio.CancelledError:
        pass
    finally:
        _queue_worker_task = None
