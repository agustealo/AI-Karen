"""
Agent UI Service

.. deprecated::
    The legacy UI service is deprecated. UI integration should use
    ``ai_karen_engine.copilotkit`` or direct API routes.
"""

import asyncio
import logging
import time
import uuid
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, AsyncGenerator

warnings.warn(
    "ai_karen_engine.agents.agent_ui_service is deprecated. "
    "Use ai_karen_engine.copilotkit or direct API routes instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.services.base import BaseService, ServiceConfig, ServiceStatus

from .agent_ui_error_handler import AgentUIErrorHandler, ErrorContext

from .agent_ui_models import (
    # Enums
    ExecutionMode,
    UIComponentType,
    ContentType,
    LayoutType,
    OutputProfile,
    
    # Request/Response Models
    SendMessageRequest,
    SendMessageResponse,
    CreateDeepTaskRequest,
    CreateDeepTaskResponse,
    GetTaskProgressRequest,
    GetTaskProgressResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    AgentUIRequest,
    AgentUIResponse,
    
    # Data Models
    InteractiveElement,
    ResponseMetadata,
    TaskProgress,
    AgentUIError,
    AgentUIServiceConfig,
    AgentUIServiceStatus,
    AgentUIServiceMetrics
)

from .internal.agent_schemas import AgentTask, TaskStatus


class AgentUIServiceInterface:
    """
    Interface for the Agent UI Service.
    
    This interface defines the contract for the Agent UI Service,
    ensuring consistency across different implementations.
    """
    
    async def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        """
        Send a message to an agent.
        
        Args:
            request: The send message request
            
        Returns:
            The send message response
        """
        raise NotImplementedError("send_message not implemented")
    
    async def create_deep_task(self, request: CreateDeepTaskRequest) -> CreateDeepTaskResponse:
        """
        Create a deep task that uses DeepAgents.
        
        Args:
            request: The create deep task request
            
        Returns:
            The create deep task response
        """
        raise NotImplementedError("create_deep_task not implemented")
    
    async def get_task_progress(self, request: GetTaskProgressRequest) -> GetTaskProgressResponse:
        """
        Get progress of a running task.
        
        Args:
            request: The get task progress request
            
        Returns:
            The task progress response
        """
        raise NotImplementedError("get_task_progress not implemented")
    
    async def cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """
        Cancel a running task.
        
        Args:
            request: The cancel task request
            
        Returns:
            The cancel task response
        """
        raise NotImplementedError("cancel_task not implemented")
    
    async def process_request(self, request: AgentUIRequest) -> AgentUIResponse:
        """
        Process a generic agent UI request.
        
        Args:
            request: The agent UI request
            
        Returns:
            The agent UI response
        """
        raise NotImplementedError("process_request not implemented")
    
    async def get_service_status(self) -> AgentUIServiceStatus:
        """
        Get the status of the Agent UI Service.
        
        Returns:
            The service status
        """
        raise NotImplementedError("get_service_status not implemented")
    
    async def get_service_metrics(self) -> AgentUIServiceMetrics:
        """
        Get the metrics of the Agent UI Service.
        
        Returns:
            The service metrics
        """
        raise NotImplementedError("get_service_metrics not implemented")


class AgentUIService(BaseService, AgentUIServiceInterface):
    """
    Agent UI Service implementation.
    
    This service provides the interface layer between the UI and the agent system,
    handling UI interactions, task creation, and response formatting.
    """
    
    def __init__(self, config: Optional[AgentUIServiceConfig] = None):
        """
        Initialize the Agent UI Service.
        
        Args:
            config: Configuration for the service
        """
        service_config = ServiceConfig(
            name=config.service_name if config else "agent_ui_service"
        )
        super().__init__(service_config)
        
        self._config = config or AgentUIServiceConfig()
        self._initialized = False
        self._start_time = datetime.utcnow()
        
        # Service state
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._active_tasks_count = 0
        self._lock = asyncio.Lock()
        
        # Metrics
        self._metrics = AgentUIServiceMetrics()
        
        # Dependencies (to be injected)
        self._agent_orchestrator = None
        self._thread_manager = None
        self._session_state_manager = None
        self._response_formatter = None
        
        # Error handler
        self._error_handler = AgentUIErrorHandler(self.logger)
        
        # Set up logging
        self.logger = logging.getLogger(self._config.service_name)
        if self._config.enable_logging:
            self.logger.setLevel(getattr(logging, self._config.log_level))
    
    async def initialize(self) -> bool:
        """
        Initialize the Agent UI Service.
        
        Returns:
            True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing Agent UI Service")
            
            # Validate dependencies
            if not self._agent_orchestrator:
                raise RuntimeError("Agent orchestrator is required")
            
            if not self._thread_manager:
                raise RuntimeError("Thread manager is required")
            
            if not self._session_state_manager:
                raise RuntimeError("Session state manager is required")
            
            if not self._response_formatter:
                raise RuntimeError("Response formatter is required")
            
            # Initialize service state
            self._initialized = True
            self._status = ServiceStatus.RUNNING
            
            self.logger.info("Agent UI Service initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Agent UI Service: {e}")
            self._status = ServiceStatus.ERROR
            return False
    
    async def shutdown(self) -> bool:
        """
        Shutdown the Agent UI Service.
        
        Returns:
            True if shutdown was successful, False otherwise
        """
        try:
            self.logger.info("Shutting down Agent UI Service")
            
            # Clear service state
            async with self._lock:
                self._sessions.clear()
                self._tasks.clear()
                self._active_tasks_count = 0
            
            self._initialized = False
            self._status = ServiceStatus.STOPPED
            
            self.logger.info("Agent UI Service shutdown successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to shutdown Agent UI Service: {e}")
            return False
    
    async def health_check(self) -> bool:
        """
        Check the health of the Agent UI Service.
        
        Returns:
            True if the service is healthy, False otherwise
        """
        return self._initialized and self._status == ServiceStatus.RUNNING
    
    # Dependency injection methods
    
    def set_agent_orchestrator(self, agent_orchestrator: Any) -> None:
        """
        Set the agent orchestrator dependency.
        
        Args:
            agent_orchestrator: The agent orchestrator
        """
        self._agent_orchestrator = agent_orchestrator
    
    def set_thread_manager(self, thread_manager: Any) -> None:
        """
        Set the thread manager dependency.
        
        Args:
            thread_manager: The thread manager
        """
        self._thread_manager = thread_manager
    
    def set_session_state_manager(self, session_state_manager: Any) -> None:
        """
        Set the session state manager dependency.
        
        Args:
            session_state_manager: The session state manager
        """
        self._session_state_manager = session_state_manager
    
    def set_response_formatter(self, response_formatter: Any) -> None:
        """
        Set the response formatter dependency.
        
        Args:
            response_formatter: The response formatter
        """
        self._response_formatter = response_formatter
    
    # Service interface methods
    
    async def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        """
        Send a message to an agent.
        
        Args:
            request: The send message request
            
        Returns:
            The send message response
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Update metrics
            self._metrics.requests_received += 1
            self._metrics.messages_sent += 1
            
            # Get or create thread for session
            thread_id = request.thread_id
            if not thread_id:
                thread_id = await self._thread_manager.get_langgraph_thread(request.session_id)
                if not thread_id:
                    thread_id = await self._thread_manager.create_thread(request.session_id)
            
            # Create agent task
            task_id = str(uuid.uuid4())
            agent_task = AgentTask(
                task_id=task_id,
                agent_id=request.agent_id or "default",
                task_type="message",
                description="Process user message",
                input_data={
                    "message": request.message,
                    "context": request.context,
                    "execution_mode": request.execution_mode.value
                },
                status=TaskStatus.PENDING,
                priority=request.priority,
                timeout_seconds=request.timeout_seconds or self._config.default_timeout_seconds,
                metadata=request.metadata
            )
            
            # Store task
            async with self._lock:
                self._tasks[task_id] = {
                    "task": agent_task,
                    "session_id": request.session_id,
                    "thread_id": thread_id,
                    "start_time": time.time()
                }
                self._active_tasks_count += 1
            
            # Update metrics
            self._metrics.tasks_created += 1
            
            # Submit task to agent orchestrator
            task_result = await self._agent_orchestrator.execute_task(agent_task)
            
            # Update task status
            agent_task.status = task_result.status if hasattr(task_result, 'status') else TaskStatus.COMPLETED
            agent_task.result = task_result.data if hasattr(task_result, 'data') else {"response": str(task_result)}
            
            # Create response metadata
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.TEXT,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                execution_time=time.time() - self._tasks[task_id]["start_time"],
                agent_id=agent_task.agent_id,
                task_id=task_id,
                session_id=request.session_id,
                thread_id=thread_id
            )
            
            # Update metrics
            self._metrics.requests_processed += 1
            self._metrics.tasks_completed += 1
            self._active_tasks_count -= 1
            
            return SendMessageResponse(
                success=True,
                message_id=str(uuid.uuid4()),
                task_id=task_id,
                response=str(task_result),
                is_streaming=False,
                metadata=metadata
            )
        except Exception as e:
            # Update metrics
            self._metrics.requests_failed += 1
            self._metrics.tasks_failed += 1
            self._active_tasks_count -= 1
            self._metrics.errors_encountered += 1
            
            self.logger.error(f"Error sending message: {e}")
            
            # Create error response
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.TEXT,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                has_error=True
            )
            
            return SendMessageResponse(
                success=False,
                message_id=str(uuid.uuid4()),
                response=None,
                is_streaming=False,
                metadata=metadata,
                error=str(e)
            )
    
    async def create_deep_task(self, request: CreateDeepTaskRequest) -> CreateDeepTaskResponse:
        """
        Create a deep task that uses DeepAgents.
        
        Args:
            request: The create deep task request
            
        Returns:
            The create deep task response
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Update metrics
            self._metrics.requests_received += 1
            
            # Get or create thread for session
            thread_id = request.thread_id
            if not thread_id:
                thread_id = await self._thread_manager.get_langgraph_thread(request.session_id)
                if not thread_id:
                    thread_id = await self._thread_manager.create_thread(request.session_id)
            
            # Create agent task
            task_id = str(uuid.uuid4())
            agent_task = AgentTask(
                task_id=task_id,
                agent_id=request.agent_id or "deep_agents",
                task_type=request.task_type,
                description=request.description,
                input_data=request.input_data,
                expected_output=request.expected_output,
                status=TaskStatus.PENDING,
                priority=request.priority,
                timeout_seconds=request.timeout_seconds or self._config.default_timeout_seconds,
                metadata=request.metadata
            )
            
            # Store task
            async with self._lock:
                self._tasks[task_id] = {
                    "task": agent_task,
                    "session_id": request.session_id,
                    "thread_id": thread_id,
                    "start_time": time.time()
                }
                self._active_tasks_count += 1
            
            # Update metrics
            self._metrics.tasks_created += 1
            
            # Submit task to agent orchestrator with DeepAgents mode
            task_result = await self._agent_orchestrator.execute_deep_task(agent_task)
            
            # Update task status
            agent_task.status = task_result.status if hasattr(task_result, 'status') else TaskStatus.COMPLETED
            
            # Create response metadata
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                execution_time=time.time() - self._tasks[task_id]["start_time"],
                agent_id=agent_task.agent_id,
                task_id=task_id,
                session_id=request.session_id,
                thread_id=thread_id
            )
            
            # Update metrics
            self._metrics.requests_processed += 1
            self._metrics.tasks_completed += 1
            self._active_tasks_count -= 1
            
            return CreateDeepTaskResponse(
                success=True,
                task_id=task_id,
                status=agent_task.status,
                message="Deep task created successfully",
                metadata=metadata
            )
        except Exception as e:
            # Update metrics
            self._metrics.requests_failed += 1
            self._metrics.tasks_failed += 1
            self._active_tasks_count -= 1
            self._metrics.errors_encountered += 1
            
            self.logger.error(f"Error creating deep task: {e}")
            
            # Create error response
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                has_error=True
            )
            
            return CreateDeepTaskResponse(
                success=False,
                task_id=str(uuid.uuid4()),
                status=TaskStatus.FAILED,
                message=None,
                metadata=metadata,
                error=str(e)
            )
    
    async def get_task_progress(self, request: GetTaskProgressRequest) -> GetTaskProgressResponse:
        """
        Get progress of a running task.
        
        Args:
            request: The get task progress request
            
        Returns:
            The task progress response
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Update metrics
            self._metrics.requests_received += 1
            
            # Get task
            async with self._lock:
                task_info = self._tasks.get(request.task_id)
                if not task_info:
                    raise ValueError(f"Task {request.task_id} not found")
            
            agent_task = task_info["task"]
            
            # Get task progress from agent orchestrator
            progress_data = await self._agent_orchestrator.get_task_progress(request.task_id)
            
            # Create task progress object
            task_progress = TaskProgress(
                task_id=request.task_id,
                status=agent_task.status,
                progress=progress_data.get("progress", 0.0),
                message=progress_data.get("message", ""),
                steps_completed=progress_data.get("steps_completed", 0),
                total_steps=progress_data.get("total_steps"),
                current_step=progress_data.get("current_step"),
                estimated_time_remaining=progress_data.get("estimated_time_remaining"),
                details=progress_data.get("details", {})
            )
            
            # Create response metadata
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=LayoutType.SYSTEM_STATUS,
                output_profile=self._config.default_output_profile,
                agent_id=agent_task.agent_id,
                task_id=request.task_id,
                session_id=request.session_id,
                thread_id=task_info["thread_id"]
            )
            
            # Update metrics
            self._metrics.requests_processed += 1
            
            return GetTaskProgressResponse(
                success=True,
                task_progress=task_progress,
                metadata=metadata
            )
        except Exception as e:
            # Update metrics
            self._metrics.requests_failed += 1
            self._metrics.errors_encountered += 1
            
            self.logger.error(f"Error getting task progress: {e}")
            
            # Create error response
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=LayoutType.SYSTEM_STATUS,
                output_profile=self._config.default_output_profile,
                has_error=True
            )
            
            return GetTaskProgressResponse(
                success=False,
                task_progress=TaskProgress(
                    task_id=request.task_id,
                    status=TaskStatus.FAILED,
                    progress=0.0,
                    message=str(e)
                ),
                metadata=metadata,
                error=str(e)
            )
    
    async def cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """
        Cancel a running task.
        
        Args:
            request: The cancel task request
            
        Returns:
            The cancel task response
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Update metrics
            self._metrics.requests_received += 1
            
            # Get task
            async with self._lock:
                task_info = self._tasks.get(request.task_id)
                if not task_info:
                    raise ValueError(f"Task {request.task_id} not found")
            
            agent_task = task_info["task"]
            
            # Cancel task with agent orchestrator
            cancel_result = await self._agent_orchestrator.cancel_task(request.task_id, request.reason)
            
            # Update task status
            agent_task.status = TaskStatus.CANCELLED
            
            # Create response metadata
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                agent_id=agent_task.agent_id,
                task_id=request.task_id,
                session_id=request.session_id,
                thread_id=task_info["thread_id"]
            )
            
            # Update metrics
            self._metrics.requests_processed += 1
            self._metrics.tasks_cancelled += 1
            self._active_tasks_count -= 1
            
            return CancelTaskResponse(
                success=True,
                task_id=request.task_id,
                status=TaskStatus.CANCELLED,
                message="Task cancelled successfully",
                metadata=metadata
            )
        except Exception as e:
            # Update metrics
            self._metrics.requests_failed += 1
            self._metrics.errors_encountered += 1
            
            self.logger.error(f"Error cancelling task: {e}")
            
            # Create error response
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                has_error=True
            )
            
            return CancelTaskResponse(
                success=False,
                task_id=request.task_id,
                status=TaskStatus.FAILED,
                message=None,
                metadata=metadata,
                error=str(e)
            )
    
    async def process_request(self, request: AgentUIRequest) -> AgentUIResponse:
        """
        Process a generic agent UI request.
        
        Args:
            request: The agent UI request
            
        Returns:
            The agent UI response
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Update metrics
            self._metrics.requests_received += 1
            
            # Process request based on type
            if request.request_type == "send_message":
                send_request = SendMessageRequest(
                    session_id=request.session_id,
                    thread_id=request.thread_id,
                    message=request.data.get("message", ""),
                    context=request.data.get("context", {}),
                    execution_mode=ExecutionMode(request.data.get("execution_mode", "auto")),
                    agent_id=request.data.get("agent_id"),
                    priority=request.data.get("priority", 0),
                    timeout_seconds=request.data.get("timeout_seconds"),
                    metadata=request.metadata
                )
                send_response = await self.send_message(send_request)
                
                return AgentUIResponse(
                    success=send_response.success,
                    request_type=request.request_type,
                    data={
                        "message_id": send_response.message_id,
                        "task_id": send_response.task_id,
                        "response": send_response.response,
                        "is_streaming": send_response.is_streaming
                    },
                    metadata=send_response.metadata,
                    error=send_response.error
                )
            
            elif request.request_type == "create_deep_task":
                create_request = CreateDeepTaskRequest(
                    session_id=request.session_id,
                    thread_id=request.thread_id,
                    task_type=request.data.get("task_type", ""),
                    description=request.data.get("description"),
                    input_data=request.data.get("input_data", {}),
                    context=request.data.get("context", {}),
                    agent_id=request.data.get("agent_id"),
                    priority=request.data.get("priority", 0),
                    timeout_seconds=request.data.get("timeout_seconds"),
                    expected_output=request.data.get("expected_output"),
                    metadata=request.metadata
                )
                create_response = await self.create_deep_task(create_request)
                
                return AgentUIResponse(
                    success=create_response.success,
                    request_type=request.request_type,
                    data={
                        "task_id": create_response.task_id,
                        "status": create_response.status.value,
                        "message": create_response.message
                    },
                    metadata=create_response.metadata,
                    error=create_response.error
                )
            
            elif request.request_type == "get_task_progress":
                progress_request = GetTaskProgressRequest(
                    session_id=request.session_id,
                    task_id=request.data.get("task_id", ""),
                    include_details=request.data.get("include_details", False),
                    metadata=request.metadata
                )
                progress_response = await self.get_task_progress(progress_request)
                
                return AgentUIResponse(
                    success=progress_response.success,
                    request_type=request.request_type,
                    data={
                        "task_progress": progress_response.task_progress.model_dump()
                    },
                    metadata=progress_response.metadata,
                    error=progress_response.error
                )
            
            elif request.request_type == "cancel_task":
                cancel_request = CancelTaskRequest(
                    session_id=request.session_id,
                    task_id=request.data.get("task_id", ""),
                    reason=request.data.get("reason"),
                    metadata=request.metadata
                )
                cancel_response = await self.cancel_task(cancel_request)
                
                return AgentUIResponse(
                    success=cancel_response.success,
                    request_type=request.request_type,
                    data={
                        "task_id": cancel_response.task_id,
                        "status": cancel_response.status.value,
                        "message": cancel_response.message
                    },
                    metadata=cancel_response.metadata,
                    error=cancel_response.error
                )
            
            else:
                raise ValueError(f"Unknown request type: {request.request_type}")
        
        except Exception as e:
            # Update metrics
            self._metrics.requests_failed += 1
            self._metrics.errors_encountered += 1
            
            self.logger.error(f"Error processing request: {e}")
            
            # Create error response
            metadata = ResponseMetadata(
                response_id=str(uuid.uuid4()),
                content_type=ContentType.JSON,
                layout_type=self._config.default_layout_type,
                output_profile=self._config.default_output_profile,
                has_error=True
            )
            
            return AgentUIResponse(
                success=False,
                request_type=request.request_type,
                data={},
                metadata=metadata,
                error=str(e)
            )
    
    async def get_service_status(self) -> AgentUIServiceStatus:
        """
        Get the status of the Agent UI Service.
        
        Returns:
            The service status
        """
        uptime = (datetime.utcnow() - (self._start_time or datetime.utcnow())).total_seconds()
        
        return AgentUIServiceStatus(
            service_name=self._config.service_name,
            status=self._status.value if self._status else "unknown",
            is_healthy=await self.health_check(),
            uptime_seconds=uptime,
            active_sessions=len(self._sessions),
            active_tasks=self._active_tasks_count,
            last_activity=datetime.utcnow() if self._tasks else None,
            version="1.0.0"
        )
    
    async def get_service_metrics(self) -> AgentUIServiceMetrics:
        """
        Get the metrics of the Agent UI Service.
        
        Returns:
            The service metrics
        """
        # Update active sessions count
        self._metrics.sessions_active = len(self._sessions)
        
        return self._metrics
    
    async def stream_task_progress(self, task_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream progress updates for a task.
        
        Args:
            task_id: The ID of the task to stream
            
        Yields:
            Progress update dictionaries
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Service is not initialized")
        
        try:
            # Get task
            async with self._lock:
                task_info = self._tasks.get(task_id)
                if not task_info:
                    raise ValueError(f"Task {task_id} not found")
            
            agent_task = task_info["task"]
            
            # Stream progress from agent orchestrator
            async for progress_update in self._agent_orchestrator.stream_task_progress(task_id):
                # Update metrics
                self._metrics.streaming_responses += 1
                
                # Yield progress update
                yield {
                    "task_id": task_id,
                    "status": agent_task.status.value,
                    "progress": progress_update.get("progress", 0.0),
                    "message": progress_update.get("message", ""),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Check if task is completed
                if agent_task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    break
        except Exception as e:
            # Create error context
            error_context = ErrorContext(
                task_id=task_id,
                operation="stream_task_progress",
                component="AgentUIService"
            )
            
            # Handle error
            handled_error = await self._error_handler.handle_error(e, error_context)
            
            yield {
                "task_id": task_id,
                "status": TaskStatus.FAILED.value,
                "progress": 0.0,
                "message": self._error_handler.get_user_friendly_error_message(handled_error),
                "timestamp": datetime.utcnow().isoformat(),
                "error": True,
                "error_code": handled_error.error_code,
                "error_severity": handled_error.severity
            }
    
    async def start(self) -> bool:
        """
        Start the service.
        
        Returns:
            True if the service was started successfully, False otherwise
        """
        return await self.initialize()
    
    async def stop(self) -> bool:
        """
        Stop the service.
        
        Returns:
            True if the service was stopped successfully, False otherwise
        """
        return await self.shutdown()