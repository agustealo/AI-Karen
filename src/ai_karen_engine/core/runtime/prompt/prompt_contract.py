"""
PromptRuntime contracts.

Defines the canonical data structures for prompt assembly, versioning,
and metadata. All prompt assembly flows through these contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PromptAssemblyRequest:
    """Inputs for prompt assembly."""

    system_policy: str = ""
    tenant_policy: str = ""
    persona: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    memory_items: List[Dict[str, Any]] = field(default_factory=list)
    cortex_intent: Dict[str, Any] = field(default_factory=dict)
    tool_contracts: List[Dict[str, Any]] = field(default_factory=list)
    workflow_context: Dict[str, Any] = field(default_factory=dict)
    provider_capabilities: Dict[str, Any] = field(default_factory=dict)
    token_budget: int = 4096
    output_schema: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None


@dataclass
class PromptAssemblyResult:
    """Output of prompt assembly."""

    messages: List[Dict[str, Any]]
    prompt_id: Optional[str]
    prompt_version: Optional[str]
    prompt_hash: str
    included_memory_refs: List[str] = field(default_factory=list)
    included_tool_contracts: List[str] = field(default_factory=list)
    token_estimate: int = 0
    truncation_events: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptDefinition:
    """Registered prompt template/contract."""

    prompt_id: str
    version: str
    system_policy: str = ""
    tenant_policy: str = ""
    persona: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    tool_contracts: List[Dict[str, Any]] = field(default_factory=list)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    token_budget: int = 4096
    metadata: Dict[str, Any] = field(default_factory=dict)
