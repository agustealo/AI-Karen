"""
Agent Lifecycle Manager

.. deprecated::
    The legacy lifecycle manager is deprecated. Agent lifecycle is now handled
    by ``ai_karen_engine.agent_medusa.lifecycle.lifecycle_manager`` and the
    canonical specialist registry.
"""

import asyncio
import logging
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4

warnings.warn(
    "ai_karen_engine.agents.lifecycle_manager is deprecated. "
    "Use ai_karen_engine.agent_medusa.lifecycle instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .models import (
    AgentInfo,
    AgentStatus,
    AgentLifecycleEvent,
    AgentExecutionMode,
    AgentCapability,
    AgentMetrics,
    AgentConfig,
)

logger = logging.getLogger(__name__)


class AgentLifecycleManager:
    """Manages the lifecycle of agents."""
    
    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._lifecycle_events: List[AgentLifecycleEvent] = []
        self._max_events = 1000  # Maximum events to keep in memory
        self._cleanup_interval = 300  # Cleanup interval in seconds (5 minutes)
        self._agent_timeout = 3600  # Agent timeout in seconds (1 hour)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(f"{__name__}.AgentLifecycleManager")
    
    async def initialize(self):
        """Initialize the lifecycle manager."""
        self.logger.info("Initializing Agent Lifecycle Manager")
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # Initialize default agents for each execution mode
        await self._initialize_default_agents()
        
        self.logger.info("Agent Lifecycle Manager initialized")
    
    async def shutdown(self):
        """Shutdown the lifecycle manager."""
        self.logger.info("Shutting down Agent Lifecycle Manager")
        
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Terminate all agents
        await self.terminate_all_agents()
        
        self.logger.info("Agent Lifecycle Manager shutdown complete")
    
    async def _initialize_default_agents(self):
        """Initialize default agents for each execution mode."""
        default_configs = {
            AgentExecutionMode.NATIVE: AgentConfig(
                execution_mode=AgentExecutionMode.NATIVE,
                model_name="default",
                provider="default",
                capabilities=[
                    AgentCapability.TEXT_GENERATION,
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.ANALYSIS,
                    AgentCapability.REASONING,
                    AgentCapability.STREAMING
                ]
            ),
            AgentExecutionMode.LANGGRAPH: AgentConfig(
                execution_mode=AgentExecutionMode.LANGGRAPH,
                model_name="langgraph_default",
                capabilities=[
                    AgentCapability.TEXT_GENERATION,
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.ANALYSIS,
                    AgentCapability.REASONING,
                    AgentCapability.MEMORY_ACCESS,
                    AgentCapability.TOOL_USE,
                    AgentCapability.STREAMING
                ]
            ),
            AgentExecutionMode.DEEP_AGENTS: AgentConfig(
                execution_mode=AgentExecutionMode.DEEP_AGENTS,
                model_name="deep_agents_default",
                capabilities=[
                    AgentCapability.TEXT_GENERATION,
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.ANALYSIS,
                    AgentCapability.REASONING,
                    AgentCapability.MEMORY_ACCESS,
                    AgentCapability.TOOL_USE,
                    AgentCapability.MULTIMODAL,
                    AgentCapability.STREAMING
                ]
            )
        }
        
        for mode, config in default_configs.items():
            agent_id = f"default_{mode.value}_agent"
            await self.create_agent(
                agent_id=agent_id,
                name=f"Default {mode.value.title()} Agent",
                description=f"Default agent for {mode.value} execution mode",
                execution_mode=mode,
                config=config
            )
    
    async def create_agent(
        self,
        agent_id: str,
        name: str,
        description: str,
        execution_mode: AgentExecutionMode,
        config: AgentConfig
    ) -> AgentInfo:
        """Create a new agent."""
        async with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent with ID {agent_id} already exists")
            
            # Create agent info
            agent_info = AgentInfo(
                agent_id=agent_id,
                name=name,
                description=description,
                execution_mode=execution_mode,
                status=AgentStatus.INITIALIZING,
                capabilities=config.capabilities,
                config=config,
                metrics=AgentMetrics(
                    agent_id=agent_id,
                    execution_mode=execution_mode
                )
            )
            
            # Store agent
            self._agents[agent_id] = agent_info
            
            # Record lifecycle event
            await self._record_lifecycle_event(
                agent_id=agent_id,
                event_type="agent_created",
                status_to=AgentStatus.INITIALIZING,
                metadata={"name": name, "execution_mode": execution_mode.value}
            )
            
            # Initialize agent
            try:
                # Here you would initialize the actual agent resources
                # For now, we'll just mark it as idle
                agent_info.status = AgentStatus.IDLE
                agent_info.last_activity = datetime.utcnow()
                
                await self._record_lifecycle_event(
                    agent_id=agent_id,
                    event_type="agent_initialized",
                    status_from=AgentStatus.INITIALIZING,
                    status_to=AgentStatus.IDLE
                )
                
                self.logger.info(f"Created agent: {agent_id}")
                
            except Exception as e:
                agent_info.status = AgentStatus.ERROR
                await self._record_lifecycle_event(
                    agent_id=agent_id,
                    event_type="agent_initialization_failed",
                    status_from=AgentStatus.INITIALIZING,
                    status_to=AgentStatus.ERROR,
                    metadata={"error": str(e)}
                )
                raise
            
            return agent_info
    
    async def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent information by ID."""
        async with self._lock:
            return self._agents.get(agent_id)
    
    async def get_all_agents(self) -> List[AgentInfo]:
        """Get all agents."""
        async with self._lock:
            return list(self._agents.values())
    
    async def get_agents_by_execution_mode(self, execution_mode: AgentExecutionMode) -> List[AgentInfo]:
        """Get agents by execution mode."""
        async with self._lock:
            return [agent for agent in self._agents.values() if agent.execution_mode == execution_mode]
    
    async def get_agents_by_status(self, status: AgentStatus) -> List[AgentInfo]:
        """Get agents by status."""
        async with self._lock:
            return [agent for agent in self._agents.values() if agent.status == status]
    
    async def update_agent_status(
        self,
        agent_id: str,
        new_status: AgentStatus,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Update agent status."""
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False
            
            old_status = agent.status
            agent.status = new_status
            agent.last_activity = datetime.utcnow()
            
            await self._record_lifecycle_event(
                agent_id=agent_id,
                event_type="status_changed",
                status_from=old_status,
                status_to=new_status,
                metadata=metadata
            )
            
            self.logger.info(f"Agent {agent_id} status changed: {old_status.value} -> {new_status.value}")
            return True
    
    async def update_agent_metrics(self, agent_id: str, metrics_update: Dict) -> bool:
        """Update agent metrics."""
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False
            
            # Update metrics
            for key, value in metrics_update.items():
                if hasattr(agent.metrics, key):
                    setattr(agent.metrics, key, value)
            
            agent.last_activity = datetime.utcnow()
            
            await self._record_lifecycle_event(
                agent_id=agent_id,
                event_type="metrics_updated",
                metadata=metrics_update
            )
            
            return True
    
    async def terminate_agent(self, agent_id: str) -> bool:
        """Terminate an agent."""
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False
            
            old_status = agent.status
            agent.status = AgentStatus.TERMINATED
            agent.last_activity = datetime.utcnow()
            
            await self._record_lifecycle_event(
                agent_id=agent_id,
                event_type="agent_terminated",
                status_from=old_status,
                status_to=AgentStatus.TERMINATED
            )
            
            self.logger.info(f"Terminated agent: {agent_id}")
            return True
    
    async def terminate_all_agents(self):
        """Terminate all agents."""
        async with self._lock:
            agent_ids = list(self._agents.keys())
        
        for agent_id in agent_ids:
            await self.terminate_agent(agent_id)
    
    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent."""
        async with self._lock:
            if agent_id not in self._agents:
                return False
            
            # Terminate first if not already terminated
            agent = self._agents[agent_id]
            if agent.status != AgentStatus.TERMINATED:
                await self.terminate_agent(agent_id)
            
            # Remove from agents
            del self._agents[agent_id]
            
            await self._record_lifecycle_event(
                agent_id=agent_id,
                event_type="agent_deleted",
                metadata={"name": agent.name}
            )
            
            self.logger.info(f"Deleted agent: {agent_id}")
            return True
    
    async def get_lifecycle_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[AgentLifecycleEvent]:
        """Get lifecycle events."""
        async with self._lock:
            events = self._lifecycle_events
            
            # Filter by agent_id
            if agent_id:
                events = [e for e in events if e.agent_id == agent_id]
            
            # Filter by event_type
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            
            # Sort by timestamp (newest first)
            events.sort(key=lambda e: e.timestamp, reverse=True)
            
            # Apply limit
            if limit:
                events = events[:limit]
            
            return events
    
    async def get_available_agents(
        self,
        execution_mode: Optional[AgentExecutionMode] = None,
        capabilities: Optional[List[AgentCapability]] = None
    ) -> List[AgentInfo]:
        """Get available agents that match criteria."""
        async with self._lock:
            agents = []
            
            for agent in self._agents.values():
                # Check if agent is available
                if not agent.is_available:
                    continue
                
                # Check execution mode
                if execution_mode and agent.execution_mode != execution_mode:
                    continue
                
                # Check capabilities
                if capabilities:
                    if not all(cap in agent.capabilities for cap in capabilities):
                        continue
                
                agents.append(agent)
            
            return agents
    
    async def _record_lifecycle_event(
        self,
        agent_id: str,
        event_type: str,
        status_from: Optional[AgentStatus] = None,
        status_to: Optional[AgentStatus] = None,
        metadata: Optional[Dict] = None
    ):
        """Record a lifecycle event."""
        event = AgentLifecycleEvent(
            agent_id=agent_id,
            event_type=event_type,
            status_from=status_from,
            status_to=status_to,
            metadata=metadata
        )
        
        self._lifecycle_events.append(event)
        
        # Trim events if too many
        if len(self._lifecycle_events) > self._max_events:
            self._lifecycle_events = self._lifecycle_events[-self._max_events:]
    
    async def _cleanup_loop(self):
        """Background cleanup loop."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_inactive_agents()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cleanup loop error: {e}")
    
    async def _cleanup_inactive_agents(self):
        """Clean up inactive agents."""
        async with self._lock:
            current_time = datetime.utcnow()
            timeout_threshold = current_time - timedelta(seconds=self._agent_timeout)
            
            inactive_agents = []
            for agent_id, agent in self._agents.items():
                if (agent.last_activity and 
                    agent.last_activity < timeout_threshold and 
                    agent.status in [AgentStatus.IDLE, AgentStatus.ERROR]):
                    inactive_agents.append(agent_id)
            
            for agent_id in inactive_agents:
                await self.terminate_agent(agent_id)
                self.logger.info(f"Cleaned up inactive agent: {agent_id}")


# Global lifecycle manager instance
_lifecycle_manager: Optional[AgentLifecycleManager] = None


def get_lifecycle_manager() -> AgentLifecycleManager:
    """Get the global lifecycle manager instance."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = AgentLifecycleManager()
    return _lifecycle_manager


async def initialize_lifecycle_manager():
    """Initialize the global lifecycle manager."""
    manager = get_lifecycle_manager()
    await manager.initialize()


async def shutdown_lifecycle_manager():
    """Shutdown the global lifecycle manager."""
    manager = get_lifecycle_manager()
    await manager.shutdown()