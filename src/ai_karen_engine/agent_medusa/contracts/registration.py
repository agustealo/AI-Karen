from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .capabilities import AgentCapability
from ...core.runtime.contracts import ExecutionBudget


# Definition lifecycle is intentionally separate from runtime health (IDLE/BUSY/etc.).
class AgentLifecycleState(str):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


@dataclass
class AgentRegistration:
    """Immutable-version runtime catalog record for a Medusa agent.

    AgentRegistration carries only the authority already granted by a validated
    AgentDefinition. It does not select providers, construct prompts, expand
    permissions, or create new policy decisions.
    """

    agent_id: str
    name: str
    description: str
    capabilities: List[AgentCapability] = field(default_factory=list)
    version: str = "1.0.0"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # Runtime health/status remains separate from definition lifecycle.
    lifecycle_state: str = AgentLifecycleState.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)

    # Trusted implementation and reproducibility references.
    implementation_id: Optional[str] = None
    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    definition_hash: Optional[str] = None
    supersedes_version: Optional[str] = None
    created_by: Optional[str] = None

    # Capability and execution boundaries.
    capability_dependencies: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    allowed_plugins: List[str] = field(default_factory=list)
    reasoning_modes: List[str] = field(default_factory=list)
    output_contract: Dict[str, Any] = field(default_factory=dict)
    resource_limits: Optional[ExecutionBudget] = None
    approval_rules: Dict[str, Any] = field(default_factory=dict)
    memory_scope: str = "session"
    task_signatures: List[str] = field(default_factory=list)

    # Security and delegation ceilings. Runtime may narrow these values but must
    # never expand them beyond RuntimePolicy/parent-agent authority.
    tenant_scope: str = "single"
    required_permissions: List[str] = field(default_factory=list)
    required_roles: List[str] = field(default_factory=list)
    max_subagents: int = 4
    max_depth: int = 2
    max_parallelism: int = 4
