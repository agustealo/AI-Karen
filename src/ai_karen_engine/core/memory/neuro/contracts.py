from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MemoryClass(str, Enum):
    STM = "stm"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    LESSON = "lesson"
    QUARANTINE = "quarantine"


class MemoryActivationMode(str, Enum):
    NONE = "none"
    FAST = "fast"
    PROFILE = "profile"
    PROCEDURAL = "procedural"
    GRAPH = "graph"
    DEEP = "deep"


class GuardOutcome(str, Enum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    REJECT = "reject"
    REQUIRES_REVIEW = "requires_review"


@dataclass(slots=True)
class MemoryActivationDecision:
    mode: MemoryActivationMode = MemoryActivationMode.FAST
    reasons: list[str] = field(default_factory=list)
    max_latency_ms: int = 250
    top_k: int = 8
    include_profile: bool = False
    include_procedural: bool = False
    include_graph: bool = False
    tenant_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    correlation_id: str | None = None


@dataclass(slots=True)
class ProcedureArtifact:
    id: str
    name: str
    trigger_patterns: list[str]
    tool_sequence: list[str]
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.0
    tenant_scope: str = "tenant"
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LessonArtifact:
    id: str
    lesson_type: str
    failure_signature: str
    correction: str
    applies_to: list[str] = field(default_factory=list)
    severity: str = "medium"
    confidence: float = 0.0
    quarantine_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConsolidationDecision:
    promote: bool
    source_class: MemoryClass
    target_class: MemoryClass
    reason: str
    confidence: float
    requires_review: bool = False


@dataclass(slots=True)
class MemoryGuardDecision:
    outcome: GuardOutcome
    reasons: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    required_review: bool = False


@dataclass(slots=True)
class MemoryCandidate:
    id: str
    text: str
    memory_class: MemoryClass
    source: str
    tenant_id: str
    user_id: str
    confidence: float = 0.0
    importance: float = 0.0
    freshness: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("memory candidate tenant_id must be explicit and non-default")
