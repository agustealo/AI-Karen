"""
Agent Capability Router

.. deprecated::
    The legacy capability router is deprecated. Capability routing is now handled
    by ``ai_karen_engine.core.runtime.cortex_execution_decider`` and
    ``ai_karen_engine.agent_medusa.planning.capability_planner``.
"""

import logging
import warnings
from typing import Dict, List, Optional, Tuple

warnings.warn(
    "ai_karen_engine.agents.capability_router is deprecated. "
    "Use ai_karen_engine.core.runtime and ai_karen_engine.agent_medusa instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .lifecycle_manager import get_lifecycle_manager
from .models import (
    AgentInfo,
    AgentExecutionMode,
    AgentCapability,
    AgentRequest,
    AgentConfig,
    AgentStatus,
    AgentMetrics,
)

logger = logging.getLogger(__name__)


class AgentCapabilityRouter:
    """Routes requests to appropriate agents based on capabilities."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AgentCapabilityRouter")
        self._capability_priority = {
            AgentCapability.MULTIMODAL: 100,
            AgentCapability.TOOL_USE: 90,
            AgentCapability.MEMORY_ACCESS: 80,
            AgentCapability.CODE_GENERATION: 70,
            AgentCapability.REASONING: 60,
            AgentCapability.ANALYSIS: 50,
            AgentCapability.STREAMING: 40,
            AgentCapability.TEXT_GENERATION: 30,
        }
        self._execution_mode_priority = {
            AgentExecutionMode.DEEP_AGENTS: 100,
            AgentExecutionMode.LANGGRAPH: 80,
            AgentExecutionMode.NATIVE: 60,
        }
    
    async def route_request(
        self,
        request: AgentRequest
    ) -> Tuple[Optional[AgentInfo], Dict[str, any]]:
        """
        Route a request to the most appropriate agent.
        
        Args:
            request: The agent request to route
            
        Returns:
            Tuple of (selected_agent, routing_metadata)
        """
        self.logger.info(f"Routing request {request.request_id} with capabilities: {[c.value for c in request.capabilities_required]}")
        
        # Get lifecycle manager
        lifecycle_manager = get_lifecycle_manager()
        
        # Get available agents
        available_agents = await lifecycle_manager.get_available_agents(
            execution_mode=request.execution_mode,
            capabilities=request.capabilities_required
        )
        
        if not available_agents:
            self.logger.warning(f"No available agents found for request {request.request_id}")
            return None, {
                "reason": "no_available_agents",
                "required_capabilities": [c.value for c in request.capabilities_required],
                "preferred_execution_mode": request.execution_mode.value
            }
        
        # Score agents based on various criteria
        scored_agents = []
        for agent in available_agents:
            score = await self._score_agent(agent, request)
            scored_agents.append((agent, score))
        
        # Sort by score (highest first)
        scored_agents.sort(key=lambda x: x[1], reverse=True)
        
        # Select best agent
        selected_agent, score = scored_agents[0]
        
        routing_metadata = {
            "selected_agent_id": selected_agent.agent_id,
            "selected_agent_name": selected_agent.name,
            "execution_mode": selected_agent.execution_mode.value,
            "score": score,
            "total_candidates": len(available_agents),
            "all_candidates": [
                {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "execution_mode": agent.execution_mode.value,
                    "score": await self._score_agent(agent, request)
                }
                for agent, _ in scored_agents
            ],
            "routing_criteria": {
                "capabilities_matched": len(request.capabilities_required),
                "execution_mode_preference": request.execution_mode.value,
                "agent_health": selected_agent.is_healthy,
                "agent_load": selected_agent.metrics.total_requests
            }
        }
        
        self.logger.info(f"Routed request {request.request_id} to agent {selected_agent.agent_id} with score {score}")
        
        return selected_agent, routing_metadata
    
    async def _score_agent(
        self,
        agent: AgentInfo,
        request: AgentRequest
    ) -> float:
        """
        Score an agent for a specific request.
        
        Args:
            agent: The agent to score
            request: The request to score against
            
        Returns:
            Score value (higher is better)
        """
        score = 0.0
        
        # Capability matching score
        capability_score = await self._calculate_capability_score(agent, request.capabilities_required)
        score += capability_score * 0.4  # 40% weight
        
        # Execution mode preference score
        execution_mode_score = self._calculate_execution_mode_score(agent, request.execution_mode)
        score += execution_mode_score * 0.3  # 30% weight
        
        # Agent health score
        health_score = self._calculate_health_score(agent)
        score += health_score * 0.2  # 20% weight
        
        # Load balancing score
        load_score = self._calculate_load_score(agent)
        score += load_score * 0.1  # 10% weight
        
        return score
    
    async def _calculate_capability_score(
        self,
        agent: AgentInfo,
        required_capabilities: List[AgentCapability]
    ) -> float:
        """Calculate capability matching score."""
        if not required_capabilities:
            return 50.0  # Neutral score if no requirements
        
        agent_capabilities = set(agent.capabilities)
        required_set = set(required_capabilities)
        
        # Check if all required capabilities are supported
        if not required_set.issubset(agent_capabilities):
            return 0.0  # Cannot handle the request
        
        # Calculate score based on capability priority
        total_priority = sum(self._capability_priority.get(cap, 0) for cap in required_capabilities)
        max_possible_priority = sum(self._capability_priority.get(cap, 0) for cap in AgentCapability)
        
        # Normalize to 0-100 scale
        return (total_priority / max_possible_priority) * 100 if max_possible_priority > 0 else 0.0
    
    def _calculate_execution_mode_score(
        self,
        agent: AgentInfo,
        preferred_mode: AgentExecutionMode
    ) -> float:
        """Calculate execution mode preference score."""
        if agent.execution_mode == preferred_mode:
            return 100.0  # Perfect match
        
        # Return score based on mode priority
        return self._execution_mode_priority.get(agent.execution_mode, 0)
    
    def _calculate_health_score(self, agent: AgentInfo) -> float:
        """Calculate agent health score."""
        if not agent.is_healthy:
            return 0.0
        
        # Consider success rate
        if agent.metrics.total_requests > 0:
            success_rate = agent.metrics.success_rate
            return success_rate * 100.0
        
        return 80.0  # Good score for new agents with no history
    
    def _calculate_load_score(self, agent: AgentInfo) -> float:
        """Calculate load balancing score."""
        total_requests = agent.metrics.total_requests
        
        # Prefer agents with moderate load (not too idle, not overloaded)
        if total_requests == 0:
            return 60.0  # OK, but not preferred
        elif total_requests < 10:
            return 80.0  # Good load
        elif total_requests < 100:
            return 100.0  # Ideal load
        elif total_requests < 1000:
            return 70.0  # Getting busy
        else:
            return 40.0  # High load
    
    async def get_routing_recommendations(
        self,
        required_capabilities: List[AgentCapability],
        preferred_execution_mode: Optional[AgentExecutionMode] = None,
        limit: int = 5
    ) -> List[Dict[str, any]]:
        """
        Get routing recommendations for given requirements.
        
        Args:
            required_capabilities: Required capabilities
            preferred_execution_mode: Preferred execution mode
            limit: Maximum number of recommendations
            
        Returns:
            List of routing recommendations
        """
        # Get lifecycle manager
        lifecycle_manager = get_lifecycle_manager()
        
        # Get available agents
        available_agents = await lifecycle_manager.get_available_agents(
            execution_mode=preferred_execution_mode,
            capabilities=required_capabilities
        )
        
        # Create a dummy request for scoring
        dummy_request = AgentRequest(
            message="dummy",
            execution_mode=preferred_execution_mode or AgentExecutionMode.NATIVE,
            capabilities_required=required_capabilities
        )
        
        # Score and rank agents
        scored_agents = []
        for agent in available_agents:
            score = await self._score_agent(agent, dummy_request)
            scored_agents.append((agent, score))
        
        # Sort by score
        scored_agents.sort(key=lambda x: x[1], reverse=True)
        
        # Create recommendations
        recommendations = []
        for agent, score in scored_agents[:limit]:
            recommendations.append({
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "execution_mode": agent.execution_mode.value,
                "capabilities": [c.value for c in agent.capabilities],
                "score": score,
                "health": agent.is_healthy,
                "metrics": {
                    "total_requests": agent.metrics.total_requests,
                    "success_rate": agent.metrics.success_rate,
                    "average_response_time": agent.metrics.average_response_time
                }
            })
        
        return recommendations
    
    async def validate_request_feasibility(
        self,
        request: AgentRequest
    ) -> Tuple[bool, List[str]]:
        """
        Validate if a request is feasible with available agents.
        
        Args:
            request: The request to validate
            
        Returns:
            Tuple of (is_feasible, list_of_issues)
        """
        issues = []
        
        # Get lifecycle manager
        lifecycle_manager = get_lifecycle_manager()
        
        # Check if any agent supports the required capabilities
        capable_agents = await lifecycle_manager.get_available_agents(
            capabilities=request.capabilities_required
        )
        
        if not capable_agents:
            issues.append(f"No available agents support required capabilities: {[c.value for c in request.capabilities_required]}")
        
        # Check if any agent supports the preferred execution mode
        if request.execution_mode:
            mode_agents = await lifecycle_manager.get_available_agents(
                execution_mode=request.execution_mode
            )
            
            if not mode_agents:
                issues.append(f"No available agents for execution mode: {request.execution_mode.value}")
        
        # Check if any agent supports both capabilities and execution mode
        suitable_agents = await lifecycle_manager.get_available_agents(
            execution_mode=request.execution_mode,
            capabilities=request.capabilities_required
        )
        
        if not suitable_agents:
            issues.append("No available agents support both the required capabilities and preferred execution mode")
        
        return len(issues) == 0, issues


# Global capability router instance
_capability_router: Optional[AgentCapabilityRouter] = None


def get_capability_router() -> AgentCapabilityRouter:
    """Get global capability router instance."""
    global _capability_router
    if _capability_router is None:
        _capability_router = AgentCapabilityRouter()
    return _capability_router