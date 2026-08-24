"""
Agent Task Router Service

.. deprecated::
    The legacy task router is deprecated. Task routing is handled by
    ``ai_karen_engine.core.runtime.cortex_execution_decider`` and
    ``ai_karen_engine.agent_medusa.planning.capability_planner``.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import logging
import warnings

from ai_karen_engine.core.services.base import BaseService, ServiceConfig

warnings.warn(
    "ai_karen_engine.agents.agent_task_router is deprecated. "
    "Use ai_karen_engine.core.runtime and ai_karen_engine.agent_medusa instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


class AgentTaskRouter(BaseService):
    """
    Agent Task Router service for routing tasks to appropriate agents.
    
    This service classifies tasks and routes them to agents with appropriate
    capabilities, handling load balancing and task distribution.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_task_router"))
        self._initialized = False
        self._task_types = {}
        self._agent_capabilities = {}
        
    async def initialize(self) -> None:
        """Initialize Agent Task Router service."""
        if self._initialized:
            return
            
        logger.info("Initializing Agent Task Router service")
        # Add initialization logic here
        self._initialized = True
        
    async def register_task_type(self, task_type: str, config: Dict[str, Any]) -> bool:
        """
        Register a new task type with router.
        
        Args:
            task_type: Type of task
            config: Configuration for task type
            
        Returns:
            True if registration was successful
        """
        if not self._initialized:
            await self.initialize()
            
        logger.info(f"Registering task type {task_type}")
        self._task_types[task_type] = config
        return True
        
    async def register_agent_capabilities(self, agent_id: str, capabilities: List[str]) -> bool:
        """
        Register capabilities of an agent.
        
        Args:
            agent_id: Unique identifier for agent
            capabilities: List of capabilities agent supports
            
        Returns:
            True if registration was successful
        """
        if not self._initialized:
            await self.initialize()
            
        logger.info(f"Registering capabilities for agent {agent_id}")
        self._agent_capabilities[agent_id] = capabilities
        return True
        
    async def route_task(self, task_type: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route a task to appropriate agent.
        
        Args:
            task_type: Type of task to route
            task_data: Data for task execution
            
        Returns:
            Result of task routing
        """
        if not self._initialized:
            await self.initialize()
            
        logger.info(f"Routing task of type {task_type}")
        
        # Find agents with appropriate capabilities
        capable_agents = [
            agent_id for agent_id, capabilities in self._agent_capabilities.items()
            if task_type in capabilities
        ]
        
        if not capable_agents:
            return {
                "status": "failed",
                "reason": "No capable agents found",
                "task_type": task_type
            }
        
        # Simple round-robin selection
        selected_agent = capable_agents[0]
        
        return {
            "status": "routed",
            "task_type": task_type,
            "agent_id": selected_agent,
            "task_data": task_data
        }
        
    async def get_task_types(self) -> List[str]:
        """
        Get list of registered task types.
        
        Returns:
            List of task type names
        """
        if not self._initialized:
            await self.initialize()
            
        return list(self._task_types.keys())
        
    async def get_agent_capabilities(self, agent_id: str) -> Optional[List[str]]:
        """
        Get capabilities of an agent.
        
        Args:
            agent_id: Unique identifier for agent
            
        Returns:
            List of capabilities or None if agent doesn't exist
        """
        if not self._initialized:
            await self.initialize()
            
        return self._agent_capabilities.get(agent_id)
        
    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of Agent Task Router service.
        
        Returns:
            A dictionary containing health status information
        """
        return {
            "status": "healthy",
            "service": "agent_task_router",
            "timestamp": datetime.utcnow().isoformat(),
            "initialized": self._initialized,
            "task_types_count": len(self._task_types),
            "agents_count": len(self._agent_capabilities)
        }