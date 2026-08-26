"""Agent definition + versioning contracts for the canonical AgentMedusa runtime.

AgentDefinition is the editable, validation-checked source of truth. Deployed
runtime versions are materialized as AgentRegistration snapshots. AgentMedusa
coordinates multi-agent execution only; provider selection, prompt assembly,
memory persistence, plugin execution, and global policy remain owned by their
canonical runtimes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registration import AgentLifecycleState, AgentRegistration

# Security-sensitive keys must never be accepted from raw UI/config JSON.
_FORBIDDEN_CONFIG_KEYS = {
    "api_key",
    "secret",
    "token",
    "password",
    "credential",
    "connection_string",
    "authorization",
    "cookie",
    "private_key",
}

_ALLOWED_MEMORY_SCOPES = {"none", "session", "conversation", "user", "tenant"}
_ALLOWED_TENANT_SCOPES = {"single", "multi", "global"}


@dataclass
class AgentDefinition:
    """Editable, governed agent definition used to create runtime registrations."""

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

    tenant_scope: str = "single"
    required_permissions: List[str] = field(default_factory=list)
    required_roles: List[str] = field(default_factory=list)

    # Delegation ceilings. RuntimePolicy and parent execution may only narrow
    # these limits, never expand them.
    max_subagents: int = 4
    max_depth: int = 2
    max_parallelism: int = 4

    implementation_id: Optional[str] = None
    created_by: Optional[str] = None
    supersedes_version: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    lifecycle_state: str = AgentLifecycleState.DRAFT

    def validate(self) -> List[str]:
        """Fail-closed validation. Returns errors; an empty list means valid."""
        errors: List[str] = []

        if not self.agent_id or not re.fullmatch(r"[a-z0-9_]{2,64}", self.agent_id):
            errors.append("agent_id must match [a-z0-9_]{2,64}")
        if not self.name.strip():
            errors.append("name is required")
        if not self.description.strip():
            errors.append("description is required")

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

        if self.memory_scope not in _ALLOWED_MEMORY_SCOPES:
            errors.append(f"invalid memory_scope: {self.memory_scope}")
        if self.tenant_scope not in _ALLOWED_TENANT_SCOPES:
            errors.append(f"invalid tenant_scope: {self.tenant_scope}")

        if self.max_subagents < 0:
            errors.append("max_subagents must be >= 0")
        if self.max_depth < 0:
            errors.append("max_depth must be >= 0")
        if self.max_parallelism < 1:
            errors.append("max_parallelism must be >= 1")

        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            errors.append("allowed_tools must not contain duplicates")
        if len(set(self.allowed_plugins)) != len(self.allowed_plugins):
            errors.append("allowed_plugins must not contain duplicates")
        if len(set(self.required_permissions)) != len(self.required_permissions):
            errors.append("required_permissions must not contain duplicates")
        if len(set(self.required_roles)) != len(self.required_roles):
            errors.append("required_roles must not contain duplicates")

        return errors

    def canonical_payload(self) -> Dict[str, Any]:
        """Return deterministic definition data for provenance hashing."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "prompt_contract_id": self.prompt_contract_id,
            "prompt_version": self.prompt_version,
            "capabilities": list(self.capabilities),
            "capability_dependencies": list(self.capability_dependencies),
            "allowed_tools": list(self.allowed_tools),
            "allowed_plugins": list(self.allowed_plugins),
            "reasoning_modes": list(self.reasoning_modes),
            "memory_scope": self.memory_scope,
            "output_contract": self.output_contract,
            "approval_rules": self.approval_rules,
            "resource_limits": self.resource_limits,
            "tenant_scope": self.tenant_scope,
            "required_permissions": list(self.required_permissions),
            "required_roles": list(self.required_roles),
            "max_subagents": self.max_subagents,
            "max_depth": self.max_depth,
            "max_parallelism": self.max_parallelism,
            "implementation_id": self.implementation_id,
            "supersedes_version": self.supersedes_version,
            "config": self.config,
            "lifecycle_state": self.lifecycle_state,
        }

    @property
    def definition_hash(self) -> str:
        """Stable SHA-256 hash for the definition snapshot."""
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_registration(
        self,
        *,
        version: str,
        implementation_id: Optional[str] = None,
    ) -> AgentRegistration:
        """Materialize a governed runtime registration snapshot."""
        errors = self.validate()
        if errors:
            raise ValueError(f"AgentDefinition invalid: {errors}")

        from .capabilities import AgentCapability, AgentCapabilityType
        from ...core.runtime.contracts import ExecutionBudget

        caps = []
        for capability_name in self.capabilities:
            try:
                capability_type = AgentCapabilityType(capability_name)
            except ValueError:
                capability_type = AgentCapabilityType.REASONING
            caps.append(
                AgentCapability(
                    type=capability_type,
                    name=capability_name,
                    description=capability_name,
                )
            )

        resource_limits = None
        if self.resource_limits:
            resource_limits = ExecutionBudget(**self.resource_limits)

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
            definition_hash=self.definition_hash,
            supersedes_version=self.supersedes_version,
            created_by=self.created_by,
            capability_dependencies=list(self.capability_dependencies),
            allowed_tools=list(self.allowed_tools),
            allowed_plugins=list(self.allowed_plugins),
            reasoning_modes=list(self.reasoning_modes),
            output_contract=dict(self.output_contract),
            resource_limits=resource_limits,
            approval_rules=dict(self.approval_rules),
            memory_scope=self.memory_scope,
            tenant_scope=self.tenant_scope,
            required_permissions=list(self.required_permissions),
            required_roles=list(self.required_roles),
            max_subagents=self.max_subagents,
            max_depth=self.max_depth,
            max_parallelism=self.max_parallelism,
            config=dict(self.config),
        )
