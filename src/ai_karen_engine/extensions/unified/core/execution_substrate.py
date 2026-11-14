"""
Extension Execution Substrate

Provides extension execution capabilities with sandboxing, timeout management,
and result handling. This serves as the single execution substrate for the
unified extension system.
"""

import asyncio
import logging
import importlib
import importlib.util
import sys
import traceback
from typing import Any, Dict, List, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid
import signal
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as ConcurrentTimeoutError,
)

from ..database_models import ExtensionModel
from .extension_loader import LEGACY_UNIFIED_EXECUTION_DISABLED

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Execution status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRequest:
    """Extension execution request."""

    id: str
    extension_id: str
    function_name: str
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None
    priority: int = 0  # Higher number = higher priority
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionResult:
    """Execution result."""

    execution_id: str
    status: ExecutionStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    memory_usage: float = 0.0
    cpu_usage: float = 0.0
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExtensionExecutionSubstrate:
    """Unified extension execution substrate."""

    def __init__(self, max_workers: int = 10, max_concurrent: int = 5):
        self.max_workers = max_workers
        self.max_concurrent = max_concurrent

        # Thread pool for CPU-bound operations
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # Execution state
        self._running_executions: Dict[str, ExecutionRequest] = {}
        self._completed_executions: Dict[str, ExecutionResult] = {}
        self._execution_queue: asyncio.Queue = asyncio.Queue()
        self._queue_lock = asyncio.Lock()

        # Execution limits
        self._active_semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout_handlers: Dict[str, asyncio.Task] = {}

        # Extension modules cache
        self._extension_modules: Dict[str, Any] = {}

        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Control flags
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Start execution processor
        self._processor_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Never start a parallel execution processor outside PluginKernel."""
        raise PermissionError(LEGACY_UNIFIED_EXECUTION_DISABLED)

    async def shutdown(self) -> None:
        """Shutdown the execution substrate."""
        self._running = False
        self._shutdown_event.set()

        # Cancel running executions
        async with self._queue_lock:
            for execution_id in list(self._running_executions.keys()):
                await self._cancel_execution(execution_id)

        # Wait for processor to finish
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        # Shutdown thread pool
        self.executor.shutdown(wait=True)

        logger.info("Extension execution substrate shutdown")

    async def execute_extension(
        self,
        extension_id: str,
        function_name: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Reject direct unscoped execution before queuing any work."""
        del extension_id, function_name, args, kwargs, timeout, priority, metadata
        raise PermissionError(LEGACY_UNIFIED_EXECUTION_DISABLED)

    async def get_execution_status(
        self, execution_id: str
    ) -> Optional[ExecutionStatus]:
        """Get execution status."""
        if execution_id in self._running_executions:
            return ExecutionStatus.RUNNING
        elif execution_id in self._completed_executions:
            return self._completed_executions[execution_id].status
        return None

    async def get_execution_result(
        self, execution_id: str
    ) -> Optional[ExecutionResult]:
        """Get execution result."""
        return self._completed_executions.get(execution_id)

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution."""
        return await self._cancel_execution(execution_id)

    async def get_running_executions(self) -> List[ExecutionRequest]:
        """Get list of running executions."""
        return list(self._running_executions.values())

    async def get_execution_history(
        self, limit: Optional[int] = None
    ) -> List[ExecutionResult]:
        """Get execution history."""
        results = list(self._completed_executions.values())
        if limit:
            results = results[-limit:]
        return results

    async def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """Register an event handler."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.info(f"Registered event handler for: {event_type}")

    async def _execution_processor(self) -> None:
        """Main execution processor."""
        while self._running:
            try:
                # Get next execution request
                request = await asyncio.wait_for(
                    self._execution_queue.get(), timeout=1.0
                )

                # Process request
                await self._process_execution(request)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in execution processor: {e}")

    async def _process_execution(self, request: ExecutionRequest) -> None:
        """Process an execution request."""
        async with self._active_semaphore:
            try:
                # Update status to running
                request.metadata["started_at"] = datetime.now()

                # Execute the function
                result = await self._execute_function(request)

                # Store result
                execution_result = ExecutionResult(
                    execution_id=request.id,
                    status=ExecutionStatus.COMPLETED,
                    result=result,
                    execution_time=result.get("execution_time", 0.0),
                    memory_usage=result.get("memory_usage", 0.0),
                    cpu_usage=result.get("cpu_usage", 0.0),
                    logs=result.get("logs", []),
                    metadata=request.metadata,
                )

                self._completed_executions[request.id] = execution_result

            except Exception as e:
                # Handle execution failure
                execution_result = ExecutionResult(
                    execution_id=request.id,
                    status=ExecutionStatus.FAILED,
                    error=str(e),
                    execution_time=0.0,
                    memory_usage=0.0,
                    cpu_usage=0.0,
                    logs=[traceback.format_exc()],
                    metadata=request.metadata,
                )

                self._completed_executions[request.id] = execution_result

            finally:
                # Clean up
                async with self._queue_lock:
                    if request.id in self._running_executions:
                        del self._running_executions[request.id]

                if request.id in self._timeout_handlers:
                    self._timeout_handlers[request.id].cancel()
                    del self._timeout_handlers[request.id]

                # Notify event handlers
                await self._notify_event_handlers(
                    "execution_completed", execution_result
                )

    async def _execute_function(self, request: ExecutionRequest) -> Dict[str, Any]:
        """Prevent execution of a cached callable through a private method."""
        del request
        raise PermissionError(LEGACY_UNIFIED_EXECUTION_DISABLED)

    async def _load_extension_module(self, extension_id: str) -> Optional[Any]:
        """Never resolve modules via a parallel code-execution cache."""
        del extension_id
        raise PermissionError(LEGACY_UNIFIED_EXECUTION_DISABLED)

    async def _timeout_handler(self, execution_id: str, timeout: float) -> None:
        """Handle execution timeout."""
        try:
            await asyncio.sleep(timeout)

            # Check if execution is still running
            if execution_id in self._running_executions:
                await self._cancel_execution(execution_id)

                # Create timeout result
                result = ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.TIMEOUT,
                    error=f"Execution timed out after {timeout} seconds",
                    execution_time=timeout,
                    memory_usage=0.0,
                    cpu_usage=0.0,
                    logs=["Execution timed out"],
                    metadata={},
                )

                self._completed_executions[execution_id] = result

                logger.warning(f"Execution {execution_id} timed out")

        except asyncio.CancelledError:
            pass

    async def _cancel_execution(self, execution_id: str) -> bool:
        """Cancel an execution."""
        if execution_id not in self._running_executions:
            return False

        # Remove from running executions
        request = self._running_executions[execution_id]
        del self._running_executions[execution_id]

        # Create cancellation result
        result = ExecutionResult(
            execution_id=execution_id,
            status=ExecutionStatus.CANCELLED,
            error="Execution cancelled",
            execution_time=0.0,
            memory_usage=0.0,
            cpu_usage=0.0,
            logs=["Execution cancelled"],
            metadata=request.metadata,
        )

        self._completed_executions[execution_id] = result

        logger.info(f"Cancelled execution: {execution_id}")
        return True

    async def _notify_event_handlers(self, event_type: str, data: Any) -> None:
        """Notify event handlers."""
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Error in event handler: {e}")

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        return {
            "running_executions": len(self._running_executions),
            "completed_executions": len(self._completed_executions),
            "queue_size": self._execution_queue.qsize(),
            "max_workers": self.max_workers,
            "max_concurrent": self.max_concurrent,
            "active_semaphore": self._active_semaphore._value,
        }
