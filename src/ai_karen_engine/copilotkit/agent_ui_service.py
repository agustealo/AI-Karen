"""
Agent UI Service for Copilot integration.

This service is a thin UI-facing boundary between Copilot-style interactions
and the canonical LangGraph + AgentMedusa runtime.

Responsibilities:
- Translate UI interactions to AgentTask objects
- Maintain task/session/task-progress state for UI consumption
- Route all execution requests to the single runtime authority
- Format responses for UI consumption
- Reflect runtime progress/status back to the UI

This service is NOT a runtime selector and does not own orchestration policy.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.copilotkit.models import (
    AgentTask,
    CancelTaskRequest,
    CancelTaskResponse,
    CreateDeepTaskRequest,
    CreateDeepTaskResponse,
    GetTaskProgressRequest,
    GetTaskProgressResponse,
    SendMessageRequest,
    SendMessageResponse,
    TaskStatus,
    TaskStep,
    TaskType,
)

logger = logging.getLogger(__name__)


class AgentUIService:
    """
    Thin bridge between Copilot-facing UI interactions and the canonical
    LangGraph + AgentMedusa runtime.

    Responsibilities:
    - Translate UI interactions to AgentTask objects
    - Maintain session/task state for UI consumption
    - Route all requests to the runtime authority
    - Format responses for UI consumption
    - Maintain lightweight task-progress tracking

    This service does NOT:
    - choose between multiple runtime brains
    - own execution policy
    - simulate orchestration modes
    - replace LangGraph or AgentMedusa
    """

    def __init__(
        self,
        runtime_adapter: Optional[Any] = None,
        thread_manager: Optional[Any] = None,
        session_manager: Optional[Any] = None,
    ):
        """
        Initialize Agent UI Service with dependencies.

        Args:
            runtime_adapter: Canonical runtime execution adapter for
                LangGraph + AgentMedusa
            thread_manager: Optional UI/session thread bridge
            session_manager: Optional session state bridge
        """
        self.runtime_adapter = runtime_adapter
        self.thread_manager = thread_manager
        self.session_manager = session_manager

        self._tasks: Dict[str, AgentTask] = {}
        self._task_progress: Dict[str, GetTaskProgressResponse] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}

        logger.info("Agent UI Service initialized")

    async def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        """
        Send a message to the canonical runtime.

        Args:
            request: Message send request with session info and content

        Returns:
            SendMessageResponse with runtime response and execution metadata
        """
        try:
            logger.info("Processing message for session %s", request.session_id)

            agent_task = self._create_agent_task_from_message(request)
            self._tasks[agent_task.task_id] = agent_task
            self._initialize_task_progress(agent_task)

            agent_task.status = TaskStatus.RUNNING
            agent_task.updated_at = datetime.utcnow()

            progress = self._task_progress[agent_task.task_id]
            progress.status = TaskStatus.RUNNING
            progress.started_at = datetime.utcnow()
            progress.updated_at = datetime.utcnow()
            progress.progress_percentage = 15.0

            result = await self._execute_via_runtime(agent_task)
            reply = result.get("content")
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("Canonical runtime returned no message content")

            agent_task.status = TaskStatus.COMPLETED
            agent_task.updated_at = datetime.utcnow()

            progress.status = TaskStatus.COMPLETED
            progress.progress_percentage = 100.0
            progress.updated_at = datetime.utcnow()
            progress.result = result

            response = SendMessageResponse(
                success=True,
                task_id=agent_task.task_id,
                content=reply,
                execution_metadata=result.get("metadata", {}),
                thread_id=agent_task.thread_id,
            )

            logger.info(
                "Message processed successfully for task %s", agent_task.task_id
            )
            return response

        except Exception as exc:
            logger.error("Error processing message: %s", exc, exc_info=True)

            task_id = None
            if "agent_task" in locals():
                task_id = agent_task.task_id
                agent_task.status = TaskStatus.FAILED
                agent_task.updated_at = datetime.utcnow()

                if task_id in self._task_progress:
                    progress = self._task_progress[task_id]
                    progress.status = TaskStatus.FAILED
                    progress.updated_at = datetime.utcnow()
                    progress.error_message = "Canonical runtime execution failed"

            return SendMessageResponse(
                success=False,
                task_id=task_id,
                content="Karen could not complete this request.",
                execution_metadata={"error_code": "COPILOT_RUNTIME_EXECUTION_FAILED"},
            )

    async def create_deep_task(
        self,
        request: CreateDeepTaskRequest,
    ) -> CreateDeepTaskResponse:
        """
        Create a long-running AgentMedusa task.

        This retains the existing external method name for compatibility,
        but the underlying execution target is the single LangGraph +
        AgentMedusa runtime, not a separate DeepAgents system.
        """
        try:
            logger.info("Creating long-running task for session %s", request.session_id)
            if self.runtime_adapter is None:
                raise RuntimeError("Canonical agent runtime is unavailable")

            agent_task = AgentTask(
                task_id=str(uuid.uuid4()),
                session_id=request.session_id,
                task_type=request.task_type,
                content=request.content,
                context=request.context,
                priority=request.priority,
                timeout_seconds=request.timeout_seconds,
                user_id=request.user_id,
                tenant_id=request.tenant_id,
            )

            self._tasks[agent_task.task_id] = agent_task

            progress_response = GetTaskProgressResponse(
                task_id=agent_task.task_id,
                status=TaskStatus.PENDING,
                progress_percentage=0.0,
                started_at=datetime.utcnow(),
                steps=[],
                thread_id=agent_task.thread_id,
            )
            self._task_progress[agent_task.task_id] = progress_response

            background_task = asyncio.create_task(
                self._execute_long_running_task(agent_task)
            )
            self._running_tasks[agent_task.task_id] = background_task

            estimated_duration = self._estimate_task_duration(agent_task)

            response = CreateDeepTaskResponse(
                success=True,
                task_id=agent_task.task_id,
                status=TaskStatus.PENDING,
                execution_metadata={
                    "mode": "agentmedusa",
                    "runtime": "langgraph",
                    "started": True,
                },
                thread_id=agent_task.thread_id,
                estimated_duration=estimated_duration,
            )

            logger.info(
                "Long-running task created successfully: %s", agent_task.task_id
            )
            return response

        except Exception as exc:
            logger.error("Error creating long-running task: %s", exc, exc_info=True)
            return CreateDeepTaskResponse(
                success=False,
                task_id="",
                status=TaskStatus.FAILED,
                execution_metadata={"error_code": "COPILOT_RUNTIME_EXECUTION_FAILED"},
            )

    async def get_task_progress(
        self,
        request: GetTaskProgressRequest,
    ) -> GetTaskProgressResponse:
        """
        Get progress of a task.
        """
        try:
            logger.info("Getting progress for task %s", request.task_id)

            if request.task_id not in self._tasks:
                raise ValueError(f"Task {request.task_id} not found")

            progress = self._task_progress.get(request.task_id)
            if not progress:
                task = self._tasks[request.task_id]
                progress = GetTaskProgressResponse(
                    task_id=request.task_id,
                    status=getattr(task, "status", TaskStatus.PENDING),
                    progress_percentage=0.0,
                    steps=[] if request.include_steps else None,
                    thread_id=task.thread_id,
                )
                self._task_progress[request.task_id] = progress

            if (
                progress.status == TaskStatus.RUNNING
                and request.task_id in self._running_tasks
                and not self._running_tasks[request.task_id].done()
            ):
                await self._update_task_progress(request.task_id)

            logger.info(
                "Retrieved progress for task %s: %s",
                request.task_id,
                progress.status,
            )
            return progress

        except Exception as exc:
            logger.error("Error getting task progress: %s", exc, exc_info=True)
            return GetTaskProgressResponse(
                task_id=request.task_id,
                status=TaskStatus.FAILED,
                error_message=str(exc),
                execution_metadata={"error": str(exc)},
            )

    async def cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """
        Cancel a running task.
        """
        try:
            logger.info("Cancelling task %s", request.task_id)

            if request.task_id not in self._tasks:
                raise ValueError(f"Task {request.task_id} not found")

            if request.task_id in self._running_tasks:
                background_task = self._running_tasks[request.task_id]
                if not background_task.done():
                    background_task.cancel()
                self._running_tasks.pop(request.task_id, None)

            task = self._tasks[request.task_id]
            task.status = TaskStatus.CANCELLED
            task.updated_at = datetime.utcnow()

            if request.task_id in self._task_progress:
                progress = self._task_progress[request.task_id]
                progress.status = TaskStatus.CANCELLED
                progress.updated_at = datetime.utcnow()
                progress.error_message = request.reason

            response = CancelTaskResponse(
                success=True,
                task_id=request.task_id,
                message=f"Task {request.task_id} cancelled successfully",
            )

            logger.info("Task cancelled successfully: %s", request.task_id)
            return response

        except Exception as exc:
            logger.error("Error cancelling task: %s", exc, exc_info=True)
            return CancelTaskResponse(
                success=False,
                task_id=request.task_id,
                message=f"Error cancelling task: {str(exc)}",
            )

    def _create_agent_task_from_message(self, request: SendMessageRequest) -> AgentTask:
        """Create AgentTask from SendMessageRequest."""
        return AgentTask(
            task_id=str(uuid.uuid4()),
            session_id=request.session_id,
            task_type=request.task_type,
            content=request.content,
            context=request.context,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
        )

    def _initialize_task_progress(self, task: AgentTask) -> None:
        """Initialize task progress entry if missing."""
        if task.task_id not in self._task_progress:
            self._task_progress[task.task_id] = GetTaskProgressResponse(
                task_id=task.task_id,
                status=TaskStatus.PENDING,
                progress_percentage=0.0,
                started_at=datetime.utcnow(),
                steps=[],
                thread_id=task.thread_id,
            )

    async def _execute_via_runtime(self, task: AgentTask) -> Dict[str, Any]:
        """
        Execute a task through the canonical runtime authority.

        This service expects a runtime adapter that routes into
        LangGraph + AgentMedusa.
        """
        logger.info("Executing task via runtime: %s", task.task_id)

        if self.runtime_adapter is None:
            raise RuntimeError("Canonical runtime adapter is unavailable")

        if hasattr(self.runtime_adapter, "execute_task"):
            result = await self.runtime_adapter.execute_task(task)
        elif hasattr(self.runtime_adapter, "process_task"):
            result = await self.runtime_adapter.process_task(task)
        else:
            raise RuntimeError(
                "Runtime adapter does not expose a supported task execution method"
            )

        if not isinstance(result, dict):
            raise RuntimeError("Canonical runtime returned an invalid result")
        if result.get("success") is False or result.get("status") in ("failed", "error"):
            raise RuntimeError("Canonical runtime reported execution failure")
        return result

    async def _execute_long_running_task(self, task: AgentTask) -> None:
        """
        Execute a long-running task in background with progress tracking.
        """
        progress = self._task_progress[task.task_id]

        try:
            task.status = TaskStatus.RUNNING
            task.updated_at = datetime.utcnow()

            progress.status = TaskStatus.RUNNING
            progress.started_at = datetime.utcnow()
            progress.updated_at = datetime.utcnow()

            steps = [
                TaskStep(
                    step_id="step_1",
                    name="Normalization",
                    description="Normalizing UI request into runtime contract",
                    status=TaskStatus.RUNNING,
                    start_time=datetime.utcnow(),
                ),
                TaskStep(
                    step_id="step_2",
                    name="Dispatch",
                    description="Dispatching task to LangGraph + AgentMedusa runtime",
                    status=TaskStatus.PENDING,
                ),
                TaskStep(
                    step_id="step_3",
                    name="Execution",
                    description="Runtime execution in progress",
                    status=TaskStatus.PENDING,
                ),
                TaskStep(
                    step_id="step_4",
                    name="Finalization",
                    description="Finalizing result for UI consumption",
                    status=TaskStatus.PENDING,
                ),
            ]

            progress.steps = steps
            progress.progress_percentage = 10.0

            for index, step in enumerate(steps[:2]):
                step.status = TaskStatus.RUNNING
                step.start_time = datetime.utcnow()
                progress.progress_percentage = 10.0 + (index * 15.0)
                progress.updated_at = datetime.utcnow()
                await asyncio.sleep(0)
                step.status = TaskStatus.COMPLETED
                step.end_time = datetime.utcnow()
                step.duration_seconds = max(
                    0.0,
                    (step.end_time - step.start_time).total_seconds(),
                )
                step.progress_percentage = 100.0

            steps[2].status = TaskStatus.RUNNING
            steps[2].start_time = datetime.utcnow()
            progress.progress_percentage = 55.0
            progress.updated_at = datetime.utcnow()

            result = await self._execute_via_runtime(task)

            steps[2].status = TaskStatus.COMPLETED
            steps[2].end_time = datetime.utcnow()
            steps[2].duration_seconds = max(
                0.0,
                (steps[2].end_time - steps[2].start_time).total_seconds(),
            )
            steps[2].progress_percentage = 100.0

            steps[3].status = TaskStatus.RUNNING
            steps[3].start_time = datetime.utcnow()
            progress.progress_percentage = 85.0
            progress.updated_at = datetime.utcnow()
            await asyncio.sleep(0)
            steps[3].status = TaskStatus.COMPLETED
            steps[3].end_time = datetime.utcnow()
            steps[3].duration_seconds = max(
                0.0,
                (steps[3].end_time - steps[3].start_time).total_seconds(),
            )
            steps[3].progress_percentage = 100.0

            task.status = TaskStatus.COMPLETED
            task.updated_at = datetime.utcnow()

            progress.status = TaskStatus.COMPLETED
            progress.progress_percentage = 100.0
            progress.updated_at = datetime.utcnow()
            progress.result = result

            logger.info("Long-running task completed: %s", task.task_id)

        except asyncio.CancelledError:
            logger.info("Long-running task cancelled: %s", task.task_id)
            task.status = TaskStatus.CANCELLED
            task.updated_at = datetime.utcnow()

            progress.status = TaskStatus.CANCELLED
            progress.updated_at = datetime.utcnow()
            progress.error_message = "Task was cancelled"
            raise

        except Exception as exc:
            logger.error(
                "Error executing long-running task %s: %s",
                task.task_id,
                exc,
                exc_info=True,
            )
            task.status = TaskStatus.FAILED
            task.updated_at = datetime.utcnow()

            progress.status = TaskStatus.FAILED
            progress.updated_at = datetime.utcnow()
            progress.error_message = str(exc)

        finally:
            self._running_tasks.pop(task.task_id, None)

    async def _update_task_progress(self, task_id: str) -> None:
        """Update progress for a running task."""
        if task_id in self._task_progress:
            progress = self._task_progress[task_id]
            progress.updated_at = datetime.utcnow()

    def _estimate_task_duration(self, task: AgentTask) -> int:
        """
        Estimate task duration in seconds based on task type and content.
        """
        base_durations = {
            TaskType.CODE_REFACTOR: 300,
            TaskType.CODE_AUDIT: 240,
            TaskType.RESEARCH: 180,
            TaskType.ANALYSIS: 120,
            TaskType.DOCUMENTATION: 150,
            TaskType.CODE_GENERATION: 90,
            TaskType.DEBUGGING: 60,
        }

        base_duration = base_durations.get(task.task_type, 60)

        content_length = len(task.content or "")
        context_length = (
            len(task.context or []) if hasattr(task.context or [], "__len__") else 0
        )

        content_factor = min(
            2.0, max(0.5, content_length / 1000 if content_length else 0.5)
        )
        context_factor = min(
            1.5, max(0.8, context_length / 10 if context_length else 0.8)
        )

        estimated_duration = int(base_duration * content_factor * context_factor)

        logger.debug(
            "Estimated duration for task %s: %ss",
            task.task_id,
            estimated_duration,
        )
        return estimated_duration

    def get_active_tasks(
        self, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get list of active tasks.
        """
        active_tasks: List[Dict[str, Any]] = []

        for task_id, task in self._tasks.items():
            if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                if session_id is None or task.session_id == session_id:
                    progress = self._task_progress.get(task_id)
                    active_tasks.append(
                        {
                            "task_id": task_id,
                            "task_type": task.task_type,
                            "status": task.status,
                            "progress": progress.model_dump() if progress else None,
                            "created_at": task.created_at,
                        }
                    )

        return active_tasks

    def get_task_history(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get task history.
        """
        history: List[Dict[str, Any]] = []

        sorted_tasks = sorted(
            self._tasks.items(),
            key=lambda item: item[1].created_at,
            reverse=True,
        )

        for task_id, task in sorted_tasks[:limit]:
            if session_id is None or task.session_id == session_id:
                progress = self._task_progress.get(task_id)
                content_preview = (
                    task.content[:200] + "..."
                    if len(task.content) > 200
                    else task.content
                )
                history.append(
                    {
                        "task_id": task_id,
                        "task_type": task.task_type,
                        "status": task.status,
                        "content": content_preview,
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                        "progress": progress.model_dump() if progress else None,
                    }
                )

        return history
