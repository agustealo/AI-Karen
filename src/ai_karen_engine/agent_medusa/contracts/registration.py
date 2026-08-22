from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from .capabilities import AgentCapability
from ...core.runtime.contracts import ExecutionBudget

# Lifecycle states the UI needs (AGENT-LIVE-1: lifecycle as first-class subsystem).
class AgentLifecycleState(str):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


@dataclass
class AgentRegistration:
    """Represents a registered agent in the Medusa system.

    Additive fields support AGENT-LIVE-1 closure:
    - implementation_id: trusted factory key (P0-4 / A4), never arbitrary import
    - prompt_contract_id/version: PromptRegistry ref for reproducibility (A10)
    - capability_dependencies: required upstream capabilities for health (A18)
    - resource_limits: per-agent ExecutionBudget ceiling (cannot exceed policy)
    - lifecycle_state: DRAFT/ACTIVE/DISABLED/ARCHIVED (A21)
    """
    agent_id: str
    name: str
    description: str
    capabilities: List[AgentCapability] = field(default_factory=list)
    version: str = "1.0.0"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # legacy free-form status (AVAILABLE/IDLE/BUSY/...)
    lifecycle_state: str = AgentLifecycleState.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)

    # --- AGENT-LIVE-1 closure fields (additive) ---
    implementation_id: Optional[str] = None
    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    capability_dependencies: List[str] = field(default_factory=list)
    resource_limits: Optional[ExecutionBudget] = None
    approval_rules: Dict[str, Any] = field(default_factory=dict)
    memory_scope: str = "session"
