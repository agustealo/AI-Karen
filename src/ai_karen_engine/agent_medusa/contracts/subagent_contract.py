"""Governed subagent delegation contracts for AgentMedusa.

A child agent may only receive a narrowed subset of authority already granted to
its parent execution. This module describes delegation constraints; it does not
construct prompts, select providers/models, or grant permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentCapability(str, Enum):
    WEB_SEARCH = "web_search"
    CODE_INTERPRETER = "code_interpreter"
    FILE_OPERATIONS = "file_operations"
    DATABASE_ACCESS = "database_access"
    EXTENSION_PLATFORM = "extension_platform"
    REASONING = "reasoning"
    MEMORY_RETRIEVAL = "memory_retrieval"


@dataclass
class SubagentContract:
    """Fail-closed authority envelope for a specialist child agent.

    Prompt/model fields from the legacy contract remain as compatibility hints
    only. Canonical prompt resolution belongs to PromptRuntime and generation
    settings belong to the runtime/provider execution path.
    """

    agent_id: str
    role: str
    capabilities: List[AgentCapability] = field(default_factory=list)

    parent_agent_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    task_id: Optional[str] = None
    objective: str = ""

    allowed_actions: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    allowed_plugins: List[str] = field(default_factory=list)
    allowed_permissions: List[str] = field(default_factory=list)
    memory_scope: str = "session"
    resource_scope: Dict[str, Any] = field(default_factory=dict)

    policy_decision_id: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None

    max_subagents: int = 0
    remaining_depth: int = 0
    max_parallelism: int = 1
    deadline: Optional[str] = None

    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None

    # Legacy compatibility hints. These MUST NOT override PromptRuntime,
    # RuntimePolicy, ExecutionBudget, or provider configuration.
    system_prompt_template: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7

    def validate(self) -> List[str]:
        """Validate delegation bounds without inventing missing authority."""
        errors: List[str] = []
        if not self.agent_id:
            errors.append("agent_id is required")
        if not self.role:
            errors.append("role is required")
        if self.max_subagents < 0:
            errors.append("max_subagents must be >= 0")
        if self.remaining_depth < 0:
            errors.append("remaining_depth must be >= 0")
        if self.max_parallelism < 1:
            errors.append("max_parallelism must be >= 1")
        if self.max_tokens < 1:
            errors.append("max_tokens must be >= 1")
        if not 0.0 <= self.temperature <= 2.0:
            errors.append("temperature must be between 0.0 and 2.0")
        return errors

    def validate_action(self, action_type: str) -> bool:
        """Return True only for actions explicitly delegated to this child.

        An empty action allow-list means no side-effecting action authority.
        Runtime policy and ActionExecutionGate still make the final decision.
        """
        normalized = action_type.strip()
        if not normalized:
            return False
        return normalized in set(self.allowed_actions)

    def allows_capability(self, capability: AgentCapability | str) -> bool:
        """Check whether a capability is explicitly present in the child envelope."""
        value = capability.value if isinstance(capability, AgentCapability) else str(capability)
        return value in {item.value for item in self.capabilities}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "parent_agent_id": self.parent_agent_id,
            "parent_execution_id": self.parent_execution_id,
            "task_id": self.task_id,
            "objective": self.objective,
            "capabilities": [cap.value for cap in self.capabilities],
            "allowed_actions": list(self.allowed_actions),
            "allowed_tools": list(self.allowed_tools),
            "allowed_plugins": list(self.allowed_plugins),
            "allowed_permissions": list(self.allowed_permissions),
            "memory_scope": self.memory_scope,
            "resource_scope": dict(self.resource_scope),
            "policy_decision_id": self.policy_decision_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "max_subagents": self.max_subagents,
            "remaining_depth": self.remaining_depth,
            "max_parallelism": self.max_parallelism,
            "deadline": self.deadline,
            "prompt_contract_id": self.prompt_contract_id,
            "prompt_version": self.prompt_version,
        }
