"""
API Routes for Cron Jobs

Provides REST API endpoints for tracking and managing Cron-based task orchestrations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging
import uuid
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False

from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.agents import get_agent_integration_service, AgentExecutionMode
from ai_karen_engine.agents.internal.agent_schemas import AgentTask
from ai_karen_engine.services.job_service import get_job_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation/cron", tags=["automation-cron"])


class CronJobRequest(BaseModel):
    taskName: str = Field(..., description="Task or Sequence Name")
    schedule: str = Field(..., description="Cron expression")
    type: str = Field(..., description="'Task' or 'Sequence'")
    targetId: str = Field(..., description="The ID of the Task or Sequence to trigger")
    enabled: bool = Field(True, description="Whether this cron job is active")
    action: str = Field("execute", description="'execute' or 'enqueue'")


class CronJobResponse(CronJobRequest):
    id: str = Field(..., description="Unique cron job identifier")
    nextRun: str = Field(..., description="Next calculated run time")
    created_at: datetime = Field(..., description="Task creation timestamp")


# In-memory storage for demo and runtime
_cron_db: Dict[str, Dict[str, Any]] = {}
_cron_executor_task: Optional[asyncio.Task] = None
_queue_worker_task: Optional[asyncio.Task] = None


def get_cron_summary() -> Dict[str, Any]:
    """Get a summary of cron jobs for statistics."""
    jobs = list(_cron_db.values())
    enabled_jobs = [j for j in jobs if j.get("enabled")]
    
    next_job = None
    next_job_time = None
    
    if enabled_jobs:
        # Find the one that runs soonest
        # nextRun is a string like "2026-04-24 09:00 UTC"
        sorted_jobs = []
        for j in enabled_jobs:
            nr = get_next_run(j["schedule"])
            if nr and nr != "Unknown" and "Invalid" not in nr:
                try:
                    dt = datetime.strptime(nr, "%Y-%m-%d %H:%M UTC")
                    sorted_jobs.append((j, dt))
                except:
                    pass
        
        if sorted_jobs:
            sorted_jobs.sort(key=lambda x: x[1])
            next_job = sorted_jobs[0][0]["taskName"]
            next_job_time = sorted_jobs[0][1].strftime("%Y-%m-%d %H:%M UTC")

    return {
        "total_cron_jobs": len(jobs),
        "enabled_cron_jobs": len(enabled_jobs),
        "next_job": next_job,
        "next_job_time": next_job_time
    }


def get_next_run(schedule: str) -> str:
    """Calculate the next run time from a cron expression."""
    if not CRONITER_AVAILABLE:
        return "N/A"
    try:
        now = datetime.utcnow()
        cron = croniter(schedule, now)
        return cron.get_next(datetime).isoformat()
    except Exception:
        return "Invalid Schedule"


@router.post("", response_model=CronJobResponse)
async def create_cron_job(
    request: CronJobRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create a new cron job definition."""
    try:
        cron_id = f"cron_{uuid.uuid4().hex[:8]}"
        
        if CRONITER_AVAILABLE and not croniter.is_valid(request.schedule):
            raise HTTPException(status_code=400, detail="Invalid cron expression")

        cron_record = {
            "id": cron_id,
            "taskName": request.taskName,
            "schedule": request.schedule,
            "type": request.type,
            "targetId": request.targetId,
            "enabled": request.enabled,
            "nextRun": get_next_run(request.schedule),
            "created_at": datetime.utcnow(),
            "last_eval": datetime.utcnow().isoformat()
        }

        _cron_db[cron_id] = cron_record
        return CronJobResponse(**cron_record)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating cron job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create cron job: {str(e)}")


@router.get("", response_model=List[CronJobResponse])
async def list_cron_jobs(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List all configured cron jobs."""
    try:
        jobs = list(_cron_db.values())
        
        # Update next runs dynamically
        for job in jobs:
            if job.get("enabled"):
                job["nextRun"] = get_next_run(job["schedule"])
            else:
                job["nextRun"] = "Disabled"

        # Sort by creation date (newest first)
        jobs.sort(key=lambda x: x["created_at"], reverse=True)
        
        return [CronJobResponse(**j) for j in jobs]
        
    except Exception as e:
        logger.error(f"Error listing cron jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list cron jobs: {str(e)}")


@router.delete("/{cron_id}")
async def delete_cron_job(
    cron_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Delete a cron job."""
    try:
        if cron_id not in _cron_db:
            raise HTTPException(status_code=404, detail="Cron job not found")
            
        del _cron_db[cron_id]
        return {"message": f"Cron job {cron_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting cron job {cron_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete cron job: {str(e)}")


@router.put("/{cron_id}/toggle", response_model=CronJobResponse)
async def toggle_cron_job(
    cron_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Toggle a cron job enablement."""
    try:
        if cron_id not in _cron_db:
            raise HTTPException(status_code=404, detail="Cron job not found")
            
        record = _cron_db[cron_id]
        record["enabled"] = not record["enabled"]
        record["nextRun"] = get_next_run(record["schedule"]) if record["enabled"] else "Disabled"
        
        return CronJobResponse(**record)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling cron job {cron_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to toggle cron job: {str(e)}")

async def _run_cron_task(job: Dict[str, Any]):
    """Internal helper to execute or enqueue a cron job task."""
    target_id = job.get("targetId")
    job_type = job.get("type")
    cron_id = job.get("id")
    action = job.get("action", "execute")

    if action == "enqueue":
        try:
            from ai_karen_engine.services.database.repositories.queue_accessor import enqueue
            queue_name = f"cron:{job_type.lower()}:{target_id}"
            payload = {
                "cron_id": cron_id,
                "target_id": target_id,
                "job_type": job_type,
                "trigger": "cron",
            }
            item_id = await enqueue(queue_name, payload)
            if item_id:
                logger.info("Enqueued cron job %s as queue item %s", cron_id, item_id)
            else:
                logger.warning("Queue enqueue returned no item_id for cron job %s", cron_id)
        except Exception as qe:
            logger.error(f"Failed to enqueue cron job {cron_id}: {qe}")
        return

    if job_type == "Task":
        try:
            integration_service = get_agent_integration_service()
            await integration_service.initialize()
            from ai_karen_engine.api_routes.automation.tasks import _tasks_db
            task_def = _tasks_db.get(target_id)
            if task_def:
                runtime_task = AgentTask(
                    task_id=f"cron_{cron_id}_{uuid.uuid4().hex[:4]}",
                    agent_id=str(task_def.get("primaryAgent") or ""),
                    task_type=str(task_def.get("taskType") or "cron_task"),
                    description=str(task_def.get("description") or ""),
                    input_data={"task_id": target_id, "trigger": "cron", "cron_id": cron_id},
                    metadata={"source": "cron", "cron_id": cron_id}
                )
                await integration_service.execute_task(runtime_task, execution_mode=AgentExecutionMode.LANGGRAPH)
        except Exception as te:
            logger.error(f"Failed to trigger cron task {target_id}: {te}")
    elif job_type in ["Sequence", "Job"]:
        try:
            job_service = get_job_service()
            cron_user = {"user_id": "system-cron", "roles": ["admin"]}
            await job_service.execute_job(target_id, user_context=cron_user)
        except Exception as je:
            logger.error(f"Failed to trigger cron job sequence {target_id}: {je}")

async def _cron_executor_loop():
    """Background task to evaluate and run cron jobs."""
    if not CRONITER_AVAILABLE:
        logger.warning("[CRON] croniter not available - background executor disabled")
        return

    logger.info("[CRON] Background executor loop started")
    while True:
        try:
            now = datetime.utcnow()
            for job_id, job in list(_cron_db.items()):
                if not job.get("enabled"):
                    continue
                
                last_eval_str = job.get("last_eval")
                if not last_eval_str:
                    last_eval = now
                else:
                    try:
                        last_eval = datetime.fromisoformat(last_eval_str)
                    except ValueError:
                        last_eval = now

                try:
                    cron = croniter(job["schedule"], last_eval)
                    next_run = cron.get_next(datetime)
                except Exception as cron_error:
                    logger.error(f"Invalid cron schedule for {job_id}: {cron_error}")
                    continue

                if next_run > now:
                    continue

                await _run_cron_task(job)
                job["last_eval"] = now.isoformat()
                job["nextRun"] = get_next_run(job["schedule"])
            
            await asyncio.sleep(10)  # 10s precision
        except Exception as e:
            logger.error(f"Cron executor error: {e}")
            await asyncio.sleep(10)


async def _queue_worker_loop():
    """Background task to dequeue and execute queued cron work items."""
    logger.info("[QUEUE] Background worker loop started")
    worker_id = f"cron-worker-{uuid.uuid4().hex[:8]}"
    while True:
        try:
            from ai_karen_engine.services.database.repositories.queue_accessor import get_queue_client
            client = get_queue_client()
            if client is None:
                await asyncio.sleep(10)
                continue

            result = await client.dequeue("cron", worker_id)
            if not result.success or not result.data:
                await asyncio.sleep(5)
                continue

            item = result.data
            logger.info("[QUEUE] Dequeued item %s from queue %s", item.id, item.queue)
            try:
                payload = item.payload or {}
                target_id = payload.get("target_id")
                job_type = payload.get("job_type")
                cron_id = payload.get("cron_id")

                if job_type == "Task":
                    integration_service = get_agent_integration_service()
                    await integration_service.initialize()
                    from ai_karen_engine.api_routes.automation.tasks import _tasks_db
                    task_def = _tasks_db.get(target_id)
                    if task_def:
                        from ai_karen_engine.agents.internal.agent_schemas import AgentTask
                        runtime_task = AgentTask(
                            task_id=f"queue_{item.id}",
                            agent_id=str(task_def.get("primaryAgent") or ""),
                            task_type=str(task_def.get("taskType") or "cron_task"),
                            description=str(task_def.get("description") or ""),
                            input_data={"task_id": target_id, "trigger": "queue", "queue_item_id": item.id},
                            metadata={"source": "queue", "cron_id": cron_id}
                        )
                        await integration_service.execute_task(runtime_task, execution_mode=AgentExecutionMode.LANGGRAPH)
                elif job_type in ["Sequence", "Job"]:
                    job_service = get_job_service()
                    cron_user = {"user_id": "system-cron", "roles": ["admin"]}
                    await job_service.execute_job(target_id, user_context=cron_user)

                await client.ack(item.queue, item.id)
                logger.info("[QUEUE] Acknowledged item %s", item.id)
            except Exception as e:
                logger.error(f"[QUEUE] Failed to process item {item.id}: {e}")
                await client.nack(item.queue, item.id, str(e))

        except Exception as e:
            logger.error(f"[QUEUE] Worker error: {e}")
            await asyncio.sleep(10)


@router.on_event("startup")
async def _start_cron_executor() -> None:
    """Start the background cron executor once the application event loop is running."""
    global _cron_executor_task

    if _cron_executor_task and not _cron_executor_task.done():
        return

    _cron_executor_task = asyncio.create_task(_cron_executor_loop())
    logger.info("Cron executor background task started")


@router.on_event("shutdown")
async def _stop_cron_executor() -> None:
    """Stop the background cron executor during application shutdown."""
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
    """Start the background queue worker once the application event loop is running."""
    global _queue_worker_task

    if _queue_worker_task and not _queue_worker_task.done():
        return

    _queue_worker_task = asyncio.create_task(_queue_worker_loop())
    logger.info("Queue worker background task started")


@router.on_event("shutdown")
async def _stop_queue_worker() -> None:
    """Stop the background queue worker during application shutdown."""
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
