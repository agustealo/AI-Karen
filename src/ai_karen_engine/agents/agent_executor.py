"""
Agent Executor service for executing agent tasks.

.. deprecated::
    The legacy agent executor is deprecated. Use ``ai_karen_engine.agent_medusa.coordinator.MedusaCoordinator``
    for canonical specialist execution.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List, Optional
from datetime import datetime

warnings.warn(
    "ai_karen_engine.agents.agent_executor is deprecated. "
    "Use ai_karen_engine.agent_medusa.coordinator.MedusaCoordinator instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


class AgentExecutor(BaseService):
    """
    Agent Executor service for executing agent tasks.
    
    This service provides the capability to execute tasks on behalf of agents,
    managing the execution lifecycle and reporting results.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_executor"))
        self._initialized = False
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        self._task_history: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize the agent executor."""
        if self._initialized:
            return
            
        self._active_tasks = {}
        self._task_history = []
        self._initialized = True
        logger.info("Agent executor initialized successfully")
    
    async def start(self) -> None:
        """Start the agent executor."""
        logger.info("Agent executor started")
    
    async def stop(self) -> None:
        """Stop the agent executor."""
        logger.info("Agent executor stopped")
    
    async def health_check(self) -> bool:
        """Check the health of the agent executor."""
        return self._initialized
    
    async def execute_task(
        self, 
        task_id: str, 
        agent_id: str, 
        task_type: str, 
        task_data: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute a task for an agent.
        
        Args:
            task_id: Unique identifier for the task
            agent_id: Identifier of the agent to execute the task
            task_type: Type of task to execute
            task_data: Data for the task
            timeout: Optional timeout for task execution
            
        Returns:
            Task execution result
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            # Check if task is already running
            if task_id in self._active_tasks:
                return {
                    "status": "error",
                    "message": f"Task {task_id} is already running",
                    "task_id": task_id
                }
            
            # Create task record
            task_record = {
                "task_id": task_id,
                "agent_id": agent_id,
                "task_type": task_type,
                "task_data": task_data,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
                "timeout": timeout
            }
            
            self._active_tasks[task_id] = task_record
            
        try:
            # Execute the task
            result = await self._perform_task_execution(task_record)
            
            # Update task record
            async with self._lock:
                task_record["status"] = "completed"
                task_record["completed_at"] = datetime.utcnow().isoformat()
                task_record["result"] = result
                
                # Move to history
                self._task_history.append(task_record.copy())
                self._active_tasks.pop(task_id, None)
                
            return {
                "status": "completed",
                "task_id": task_id,
                "result": result
            }
            
        except Exception as e:
            # Handle task execution failure
            async with self._lock:
                task_record["status"] = "failed"
                task_record["completed_at"] = datetime.utcnow().isoformat()
                task_record["error"] = str(e)
                
                # Move to history
                self._task_history.append(task_record.copy())
                self._active_tasks.pop(task_id, None)
                
            logger.error(f"Task {task_id} execution failed: {e}")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(e)
            }
    
    async def _perform_task_execution(self, task_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform the actual task execution.
        
        Args:
            task_record: Task record containing task information
            
        Returns:
            Task execution result
        """
        # This is a placeholder for actual task execution logic
        # In a real implementation, this would delegate to the appropriate agent
        # based on the task_type and agent_id
        
        task_type = task_record["task_type"]
        task_data = task_record["task_data"]
        
        logger.info(f"Executing task {task_record['task_id']} of type {task_type}")
        
        # Simulate task execution
        await asyncio.sleep(0.1)
        
        # Return a mock result
        return {
            "status": "success",
            "output": f"Task {task_type} completed successfully",
            "processed_data": task_data
        }
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a task.
        
        Args:
            task_id: Unique identifier of the task
            
        Returns:
            Task status information or None if not found
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            # Check active tasks
            if task_id in self._active_tasks:
                return self._active_tasks[task_id].copy()
            
            # Check task history
            for task in reversed(self._task_history):
                if task["task_id"] == task_id:
                    return task.copy()
                    
            return None
    
    async def list_active_tasks(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all active tasks, optionally filtered by agent.
        
        Args:
            agent_id: Optional filter for agent ID
            
        Returns:
            List of active task information
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            tasks = list(self._active_tasks.values())
            
            if agent_id:
                tasks = [task for task in tasks if task["agent_id"] == agent_id]
                
            return tasks
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel an active task.
        
        Args:
            task_id: Unique identifier of the task to cancel
            
        Returns:
            True if cancellation was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            if task_id not in self._active_tasks:
                return False
            
            task_record = self._active_tasks[task_id]
            task_record["status"] = "cancelled"
            task_record["cancelled_at"] = datetime.utcnow().isoformat()
            
            # Move to history
            self._task_history.append(task_record.copy())
            self._active_tasks.pop(task_id, None)
            
            logger.info(f"Task {task_id} cancelled")
            return True
    
    async def get_task_history(
        self, 
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get task history, optionally filtered by agent.
        
        Args:
            agent_id: Optional filter for agent ID
            limit: Maximum number of history items to return
            
        Returns:
            List of task history records
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            history = self._task_history.copy()
            
            if agent_id:
                history = [task for task in history if task["agent_id"] == agent_id]
                
            # Return most recent tasks first
            return list(reversed(history[-limit:]))