"""
PromptRuntime contracts.

Defines the canonical data structures for prompt assembly, versioning,
and metadata. All prompt assembly flows through these contracts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PromptLifecycleStatus(str, Enum):
    """Lifecycle states for prompt definitions."""
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


@dataclass(frozen=True)
class PromptVersion:
    """Typed version object for semantic versioning."""
    
    major: int
    minor: int
    patch: int
    
    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"
    
    @classmethod
    def parse(cls, version_str: str) -> "PromptVersion":
        """Parse version string like 'v1.2.3' into PromptVersion."""
        clean = version_str.strip().lower().lstrip('v')
        parts = clean.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str}. Expected 'vX.Y.Z'")
        
        try:
            return cls(
                major=int(parts[0]),
                minor=int(parts[1]),
                patch=int(parts[2]),
            )
        except ValueError as e:
            raise ValueError(f"Invalid version numbers in {version_str}: {e}")
    
    def __lt__(self, other: "PromptVersion") -> bool:
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.patch < other.patch
    
    def __le__(self, other: "PromptVersion") -> bool:
        return self < other or self == other
    
    def __gt__(self, other: "PromptVersion") -> bool:
        return not self <= other
    
    def __ge__(self, other: "PromptVersion") -> bool:
        return not self < other


@dataclass
class PromptTruncationEvent:
    """Structured record of a truncation event during prompt assembly."""

    section: str
    reason: str
    original_tokens: int
    remaining_tokens: int
    items_removed: int
    event_id: str = ""  # Unique identifier for the event
    strategy: str = ""  # Truncation strategy used
    source_refs: List[str] = field(default_factory=list)  # References to removed items
    tokens_before: int = 0  # Total tokens before truncation
    tokens_after: int = 0  # Total tokens after truncation
    removed_refs: List[str] = field(default_factory=list)  # Specific IDs of removed items
    priority: int = 0  # Priority level of truncated section
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"trunc_{hashlib.sha256(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:8]}"
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class PromptAssemblyRequest:
    """Inputs for prompt assembly."""

    system_policy: str = ""
    tenant_policy: str = ""
    system_instructions: str = ""
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
class PromptProvenance:
    """Comprehensive provenance tracking for prompt assembly."""
    
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    registry_source: str = "internal"
    assembly_version: str = "1.0.0"
    
    # Source versioning
    system_policy_version: str = ""
    tenant_policy_version: str = ""
    persona_id: str = ""
    persona_version: str = ""
    profile_id: str = ""
    
    # Included component references
    memory_refs: List[str] = field(default_factory=list)
    tool_contract_ids: List[str] = field(default_factory=list)
    workflow_id: str = ""
    workflow_version: str = ""
    cortex_decision_id: str = ""
    
    # Budget tracking
    token_estimator: str = "DeterministicHeuristicTokenEstimator"
    token_budget: int = 0
    input_tokens_estimated: int = 0
    output_tokens_reserved: int = 0
    
    # Assembly events
    override_events: List[Dict[str, Any]] = field(default_factory=list)
    truncation_events: List[PromptTruncationEvent] = field(default_factory=list)
    
    # Metadata
    correlation_id: str = ""
    assembly_timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.correlation_id:
            self.correlation_id = hashlib.sha256(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:16]
        if self.assembly_timestamp is None:
            self.assembly_timestamp = datetime.utcnow()


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
    truncation_events: List[PromptTruncationEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[PromptProvenance] = None


@dataclass
class PromptDefinition:
    """Registered prompt template/contract."""

    prompt_id: str
    version: str
    name: str = ""
    description: str = ""
    system_instructions: str = ""
    persona_defaults: Dict[str, Any] = field(default_factory=dict)
    profile_defaults: Dict[str, Any] = field(default_factory=dict)
    tool_contracts: List[Dict[str, Any]] = field(default_factory=list)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    token_budget: int = 4096
    allowed_overrides: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Lifecycle management fields
    status: PromptLifecycleStatus = PromptLifecycleStatus.DRAFT
    created_at: Optional[datetime] = None
    deprecated_at: Optional[datetime] = None
    supersedes: Optional[str] = None  # version string this version supersedes
    is_default: bool = False  # Whether this is the default active version
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    @property
    def parsed_version(self) -> PromptVersion:
        """Get typed version object."""
        return PromptVersion.parse(self.version)
