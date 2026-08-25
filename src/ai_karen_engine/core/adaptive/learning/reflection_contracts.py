"""
Reflection / consolidation contracts for AI-Karen adaptive learning.

Defines the cognitive contracts that let Karen transform experience into
durable learning.  Reflection produces candidates; it does NOT persist directly.

This module references memory and belief interfaces via structural protocols
so that it can evolve in parallel with those domains.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# ===================================
# EXPERIENCE / REFLECTION INPUT
# ===================================

@dataclass(slots=True)
class OutcomeEvidence:
    """Semantic outcome evidence for reflection."""
    outcome_id: str
    execution_status: str
    user_feedback: str | None = None
    correction: bool = False
    completion: bool = False
    tool_success: bool | None = None
    latency_ms: float = 0.0
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExperienceEvent:
    """A single unit of experience for reflection."""
    event_id: str
    event_type: str
    description: str
    timestamp: str
    outcome: OutcomeEvidence | None = None
    user_scope: dict[str, Any] = field(default_factory=dict)
    belief_refs: list[str] = field(default_factory=list)
    goal_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    salience: float = 0.0
    explicit: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        return self.user_scope.get("tenant_id", "default")

    @property
    def user_id(self) -> str | None:
        return self.user_scope.get("user_id")


@dataclass(slots=True)
class ReflectionContext:
    """Context for a reflection session."""
    user_id: str
    tenant_id: str
    session_id: str | None = None
    conversation_id: str | None = None
    project: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    prior_candidates: list[str] = field(default_factory=list)
    active_goals: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReflectionInput:
    """Input to the reflection engine."""
    events: list[ExperienceEvent]
    context: ReflectionContext
    max_candidates: int = 20


# ===================================
# CANDIDATE TYPES
# ===================================

class ReflectionCandidateType(str, Enum):
    """Types of learning candidates."""
    PREFERENCE = "preference"
    BEHAVIOR_PATTERN = "behavior_pattern"
    PROCEDURAL_LESSON = "procedural_lesson"
    SEMANTIC_FACT = "semantic_fact"
    GOAL_UPDATE = "goal_update"
    RELATIONSHIP_INSIGHT = "relationship_insight"
    FAILURE_LESSON = "failure_lesson"
    SUCCESS_PATTERN = "success_pattern"
    NONE = "none"


class PromotionAction(str, Enum):
    """Actions for promotion gate."""
    PROMOTE = "promote"
    REINFORCE = "reinforce"
    MERGE = "merge"
    DEFER = "defer"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    DECAY = "decay"


class EvidenceSourceDiversity(str, Enum):
    """Source diversity levels."""
    SINGLE = "single"
    LIMITED = "limited"
    MODERATE = "moderate"
    HIGH = "high"


class TimeDistribution(str, Enum):
    """Time distribution patterns."""
    BURSTS = "bursts"
    STEADY = "steady"
    CLUSTERED = "clustered"
    UNKNOWN = "unknown"


# ===================================
# REFLECTION CANDIDATES
# ===================================

@dataclass(slots=True)
class FailureLessonCandidate:
    """Candidate capturing a failure lesson."""
    attempt_id: str
    expected_outcome: str
    actual_outcome: str
    failure_reason: str
    recovery: str
    final_result: str
    evidence_refs: list[str] = field(default_factory=list)
    tenant_id: str = ""
    user_id: str | None = None


@dataclass(slots=True)
class ReflectionCandidate:
    """Output of reflection: a proposed durable learning update."""
    candidate_id: str
    candidate_type: ReflectionCandidateType
    summary: str
    confidence: float
    salience: float
    evidence_refs: list[str] = field(default_factory=list)
    support_count: int = 0
    contradiction_refs: list[str] = field(default_factory=list)
    scope: str = "user"
    proposed_action: str = ""
    reason_codes: list[str] = field(default_factory=list)
    failure_lesson: FailureLessonCandidate | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    tenant_id: str = ""
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.salience = max(0.0, min(1.0, self.salience))

    @property
    def is_explicit(self) -> bool:
        return any(
            "explicit" in rc for rc in self.reason_codes
        ) or self.confidence >= 0.9


@dataclass(slots=True)
class PromotionResult:
    """Result of evaluating a reflection candidate against the promotion gate."""
    candidate_id: str
    action: PromotionAction
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evaluated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass(slots=True)
class ReflectionEvent:
    """Semantic event emitted by reflection."""
    event_type: str
    candidate_id: str | None = None
    reason: str = ""
    confidence: float = 0.0
    tenant_id: str = ""
    user_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


# ===================================
# SHARED INTERFACE PROTOCOLS
# ===================================

@runtime_checkable
class BeliefAssessmentLike(Protocol):
    """Structural interface mirroring BeliefAssessment from COG-BELIEF-1.

    Reflection depends only on this protocol, not on the concrete module,
    so the two sprints can evolve in parallel.
    """
    overall_confidence: float
    verdict: str
    reason_codes: list[str]
    evidence_refs: list[str]
    uncertainty_sources: list[str]


@runtime_checkable
class GoalContextLike(Protocol):
    """Structural interface mirroring GoalSnapshot from COG-GOAL-1.

    Reflection depends only on this protocol.
    """
    goal_id: str
    tenant_id: str
    user_id: str | None
    description: str
    state: str
    priority: str
    goal_type: str
    confidence: float
    evidence_refs: list[str]
    depends_on: list[str]
    blocks: list[str]
    conflicts_with: list[str]


@runtime_checkable
class ConsolidationPolicyLike(Protocol):
    """Structural interface for memory consolidation policy.

    Reflection proposes; memory defines what may be consolidated.
    This protocol lets reflection reference memory without depending
    on the concrete memory module.
    """
    def is_promotable(
        self,
        candidate: ReflectionCandidate,
        existing_claims: list[Any],
    ) -> tuple[bool, list[str]]:
        ...


# ===================================
# PROMOTION POLICY
# ===================================

@dataclass(slots=True)
class PromotionPolicy:
    """Threshold policy for promoting reflection candidates.

    Avoids hardcoding '3 observations = true'.
    """
    min_explicit_evidence: int = 1
    min_inferred_evidence: int = 3
    min_source_diversity: int = 2
    min_confidence_explicit: float = 0.8
    min_confidence_inferred: float = 0.7
    max_contradiction_ratio: float = 0.3
    min_salience: float = 0.4
    time_distribution_min: int = 2
    risk_threshold: float = 0.7
    tenant_isolation: bool = True


@dataclass(slots=True)
class ReflectionPolicy:
    """Configuration for the reflection engine."""
    max_events_per_session: int = 100
    detect_failures: bool = True
    detect_successes: bool = True
    detect_patterns: bool = True
    detect_preferences: bool = True
    detect_goals: bool = True
    min_confidence_for_candidate: float = 0.3
    deduplication_window_hours: float = 24.0
    promotion_policy: PromotionPolicy = field(default_factory=PromotionPolicy)


# ===================================
# ID HELPERS
# ===================================

def make_event_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


def make_candidate_id() -> str:
    return f"cand_{uuid.uuid4().hex[:12]}"


__all__ = [
    "BeliefAssessmentLike",
    "ConsolidationPolicyLike",
    "EvidenceSourceDiversity",
    "ExperienceEvent",
    "FailureLessonCandidate",
    "GoalContextLike",
    "OutcomeEvidence",
    "PromotionAction",
    "PromotionPolicy",
    "PromotionResult",
    "ReflectionCandidate",
    "ReflectionCandidateType",
    "ReflectionContext",
    "ReflectionEvent",
    "ReflectionInput",
    "ReflectionPolicy",
    "TimeDistribution",
    "make_candidate_id",
    "make_event_id",
]
