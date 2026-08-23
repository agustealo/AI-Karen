import logging
from typing import Dict, List, Optional, Any
from .contracts.registration import AgentRegistration
from .contracts.capabilities import AgentCapability, AgentCapabilityType
from .safety import get_safety_manager

logger = logging.getLogger(__name__)

class MedusaRegistry:
    """Registry for AgentMedusa specialists and agents."""
    
    def __init__(self):
        self._agents: Dict[str, AgentRegistration] = {}
        self._capability_index: Dict[AgentCapabilityType, List[str]] = {}
        self._task_signature_index: Dict[str, List[str]] = {}
        self._initialized = False
        self.safety = get_safety_manager()

    async def initialize(self):
        """Initialize the registry and register builtin agents."""
        if self._initialized:
            return
        
        logger.info("Initializing MedusaRegistry")
        # Register builtin specialists
        await self._register_builtins()
        self._initialized = True

    async def _register_builtins(self):
        """Register builtin Medusa specialists."""
        # Analyst Specialist
        analyst = AgentRegistration(
            agent_id="analyst",
            name="Analyst Specialist",
            description="Analyzes complex requests and provides structured insights.",
            implementation_id="karen.agent.analyst.native",
            prompt_contract_id="karen.agent.analyst.intent",
            prompt_version="v1",
            capabilities=[
                AgentCapability(type=AgentCapabilityType.REASONING, name="Analysis", description="Structured analysis"),
                AgentCapability(type=AgentCapabilityType.DATA_ANALYSIS, name="Data Analysis", description="Analyzing data sets")
            ]
        )
        await self.register_agent(analyst)

        # Researcher Specialist
        researcher = AgentRegistration(
            agent_id="researcher",
            name="Researcher Specialist",
            description="Performs deep research using available tools and memory.",
            implementation_id="karen.agent.researcher.native",
            prompt_contract_id="karen.agent.researcher.synthesis",
            prompt_version="v1",
            capabilities=[
                AgentCapability(type=AgentCapabilityType.RESEARCH, name="Deep Research", description="Web and memory research"),
                AgentCapability(type=AgentCapabilityType.WEB_BROWSING, name="Web Browsing", description="Accessing web information")
            ]
        )
        await self.register_agent(researcher)

    async def register_agent(self, registration: AgentRegistration):
        """Register a new agent/specialist with validation."""
        # Validate agent_id
        is_valid, error = await self.safety.validate_agent_id(registration.agent_id)
        if not is_valid:
            logger.error(f"Failed to register agent {registration.agent_id}: {error}")
            raise ValueError(error)

        self._agents[registration.agent_id] = registration
        
        # Update capability index
        for cap in registration.capabilities:
            if cap.type not in self._capability_index:
                self._capability_index[cap.type] = []
            if registration.agent_id not in self._capability_index[cap.type]:
                self._capability_index[cap.type].append(registration.agent_id)
        
        # Update task signature index
        for sig in getattr(registration, "task_signatures", []) or []:
            if sig not in self._task_signature_index:
                self._task_signature_index[sig] = []
            if registration.agent_id not in self._task_signature_index[sig]:
                self._task_signature_index[sig].append(registration.agent_id)
        
        logger.info(f"Registered agent: {registration.agent_id} ({registration.name})")

    async def get_agent(self, agent_id: str) -> Optional[AgentRegistration]:
        """Get registration for a specific agent."""
        return self._agents.get(agent_id)

    async def find_agents_by_capability(self, capability_type: AgentCapabilityType) -> List[AgentRegistration]:
        """Find agents that possess a specific capability."""
        agent_ids = self._capability_index.get(capability_type, [])
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    async def list_agents(self) -> List[AgentRegistration]:
        """List all registered agents."""
        return list(self._agents.values())

    async def get_agent_health(
        self,
        agent_id: str,
        capability_health: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Derive agent health from capability_dependencies (A18).

        An agent may be registered but unusable if a required upstream
        capability is unavailable. `capability_health(cap) -> bool` is an
        injectable checker (defaults to "all healthy"). Returns a record the
        UI can use to show DEGRADED instead of falsely AVAILABLE.
        """
        reg = self._agents.get(agent_id)
        if reg is None:
            return {"exists": False}
        deps = getattr(reg, "capability_dependencies", []) or []
        missing = [
            dep for dep in deps
            if capability_health is not None and not capability_health(dep)
        ]
        return {
            "exists": True,
            "agent_id": agent_id,
            "status": reg.status,
            "lifecycle_state": reg.lifecycle_state,
            "healthy": not missing,
            "missing_dependencies": missing,
        }

_registry: Optional[MedusaRegistry] = None

def get_medusa_registry() -> MedusaRegistry:
    """Get the global MedusaRegistry instance."""
    global _registry
    if _registry is None:
        _registry = MedusaRegistry()
    return _registry
