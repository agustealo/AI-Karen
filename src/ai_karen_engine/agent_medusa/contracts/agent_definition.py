"""Agent definition + versioning contracts (AGENT-LIVE-1 A21/A22).

Defines the canonical, validation-checked agent definition used for:
- CRUD / create-edit-disable-delete (A21)
- immutable versions (task trajectories pin agent_version)
- DRAFT vs DEPLOYED separation (editing an active agent makes a new version)
- config schema validation that fails closed on unknown security fields (A22)

Note: AgentRegistration (registration.py) is the runtime catalog record.
AgentDefinition is the editable, validated source-of-truth that produces a
registered AgentRegistration on activation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registration import AgentRegistration, AgentLifecycleState

# Security-sensitive keys that must never be accepted from raw UI JSON (A22).
_FORBIDDEN_CONFIG_KEYS = {
    "api_key",
    "secret",
    "token",
    "password",
    "credential",
    "connection_string",
}


@dataclass
class AgentDefinition:
    """Editable, validated agent definition (UI/CRUD source of truth)."""

    agent_id: str
    name: str
    description: str
    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    capability_dependencies: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    allowed_plugins: List[str] = field(default_factory=list)
    reasoning_modes: List[str] = field(default_factory=list)
    memory_scope: str = "session"
    output_contract: Dict[str, Any] = field(default_factory=dict)
    approval_rules: Dict[str, Any] = field(default_factory=dict)
    resource_limits: Dict[str, Any] = field(default_factory=dict)
    implementation_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    lifecycle_state: str = AgentLifecycleState.DRAFT

    def validate(self) -> List[str]:
        """Fail-closed validation. Returns list of errors (empty == valid)."""
        errors: List[str] = []
        if not self.agent_id or not re.fullmatch(r"[a-z0-9_]{2,64}", self.agent_id):
            errors.append("agent_id must match [a-z0-9_]{2,64}")
        if not self.name:
            errors.append("name is required")
        # Unknown security-sensitive config must fail closed (A22).
        for key in self.config:
            lowered = key.lower()
            if any(forbidden in lowered for forbidden in _FORBIDDEN_CONFIG_KEYS):
                errors.append(f"config contains forbidden security key: {key}")
        if self.lifecycle_state not in {
            AgentLifecycleState.DRAFT,
            AgentLifecycleState.ACTIVE,
            AgentLifecycleState.DISABLED,
            AgentLifecycleState.ARCHIVED,
        }:
            errors.append(f"invalid lifecycle_state: {self.lifecycle_state}")
        return errors

    def to_registration(self, *, version: str, implementation_id: Optional[str] = None) -> AgentRegistration:
        """Materialize a runtime registration (immutable version snapshot)."""
        errors = self.validate()
        if errors:
            raise ValueError(f"AgentDefinition invalid: {errors}")
        from .capabilities import AgentCapability, AgentCapabilityType

        caps = []
        for c in self.capabilities:
            try:
                caps.append(AgentCapability(type=AgentCapabilityType(c), name=c, description=c))
            except ValueError:
                caps.append(AgentCapability(type=AgentCapabilityType.REASONING, name=c, description=c))
        return AgentRegistration(
            agent_id=self.agent_id,
            name=self.name,
            description=self.description,
            capabilities=caps,
            version=version,
            lifecycle_state=self.lifecycle_state,
            implementation_id=implementation_id or self.implementation_id,
            prompt_contract_id=self.prompt_contract_id,
            prompt_version=self.prompt_version,
            capability_dependencies=list(self.capability_dependencies),
            approval_rules=self.approval_rules,
            memory_scope=self.memory_scope,
            config=self.config,
        )
