"""Canonical cross-domain cognitive contracts for AI-Karen.

This module contains only concepts that are intentionally shared across multiple
cognitive domains. Domain-specific contracts remain owned by their domain.

Authority rules:
- Reasoning owns reasoning depth semantics.
- Meta-cognition may recommend verification.
- CORTEX decides verification/behavior.
- Runtime executes the authorized decision.
- No provider, platform, persistence, HTTP, or tool implementation belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


COGNITIVE_SCHEMA_VERSION = "1.0.0"
COGNITIVE_POLICY_VERSION = "1.0.0"


class ReasoningDepth(str, Enum):
    """Canonical reasoning-depth vocabulary shared by reasoning and CORTEX."""

    NONE = "none"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


class VerificationReason(str, Enum):
    """Why cognition requires independent verification."""

    LOW_CONFIDENCE = "low_confidence"
    LOW_MEMORY_CONFIDENCE = "low_memory_confidence"
    LOW_REASONING_CONFIDENCE = "low_reasoning_confidence"
    HIGH_RISK = "high_risk"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_MEMORY = "stale_memory"
    STALE_EVIDENCE = "stale_evidence"
    EXTERNAL_FACT = "external_fact"
    FAILED_PREVIOUS_STRATEGY = "failed_previous_strategy"
    CONTEXT_INCOMPLETE = "context_incomplete"
    SOURCE_QUALITY_LOW = "source_quality_low"


@dataclass(frozen=True, slots=True)
class VerificationRequirement:
    """Single verification contract used across the cognitive pipeline.

    Meta-cognition may emit this as a recommendation. CORTEX is the authority
    that decides whether it becomes part of the final BehaviorDecision. Runtime
    is the only layer allowed to execute the verification.
    """

    required: bool = False
    reason: VerificationReason | None = None
    depth: ReasoningDepth = ReasoningDepth.STANDARD
    urgency: float = 0.0
    source_stage: str = "cortex"
    evidence_refs: tuple[str, ...] = ()
    policy_version: str = COGNITIVE_POLICY_VERSION
    schema_version: str = COGNITIVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "urgency", max(0.0, min(1.0, self.urgency)))


@dataclass(frozen=True, slots=True)
class CognitiveScope:
    """Explicit cognitive scope. Tenant identity is never implicit."""

    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("tenant_id must be explicit and cannot be 'default'")


@dataclass(frozen=True, slots=True)
class BeliefSnapshot:
    """Typed cross-domain view of current epistemic state."""

    active_claim_ids: tuple[str, ...] = ()
    disputed_claim_ids: tuple[str, ...] = ()
    epistemic_confidence: float = 1.0
    contradiction_count: int = 0
    stale: bool = False
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "epistemic_confidence",
            max(0.0, min(1.0, self.epistemic_confidence)),
        )


@dataclass(frozen=True, slots=True)
class GoalSnapshot:
    """Typed cross-domain view of goals and unfinished business."""

    active_goal_ids: tuple[str, ...] = ()
    blocked_goal_ids: tuple[str, ...] = ()
    ready_intention_ids: tuple[str, ...] = ()
    open_commitment_ids: tuple[str, ...] = ()
    priority_by_goal: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Typed summary of a ContextPlan after cognitive selection."""

    selected_ids: tuple[str, ...] = ()
    omitted_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    token_budget: int = 0
    estimated_tokens_used: int = 0
    complete: bool = True


@dataclass(frozen=True, slots=True)
class SalienceSnapshot:
    """Typed cross-domain view of attention weighting."""

    overall: float = 0.0
    activation: float = 0.0
    inhibition: float = 0.0
    salience_confidence: float = 0.0
    dominant_dimensions: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("overall", "activation", "inhibition", "salience_confidence"):
            object.__setattr__(self, name, max(0.0, min(1.0, getattr(self, name))))


@dataclass(frozen=True, slots=True)
class MemorySignalSnapshot:
    """Typed summary of recall results used by downstream cognition."""

    memory_ids: tuple[str, ...] = ()
    retrieval_confidence: float = 0.0
    degraded: bool = False
    degradation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "retrieval_confidence",
            max(0.0, min(1.0, self.retrieval_confidence)),
        )


@dataclass(frozen=True, slots=True)
class UserModelSnapshot:
    """Typed user-model signals relevant to behavior selection."""

    prefers_action_over_clarification: bool = True
    explicit_preference_refs: tuple[str, ...] = ()
    inferred_preference_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationshipSnapshot:
    """Typed relationship-continuity signals relevant to cognition."""

    relationship_ids: tuple[str, ...] = ()
    shared_project_refs: tuple[str, ...] = ()
    unresolved_thread_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdaptiveRecommendationSnapshot:
    """One governed Adaptive recommendation consumed by CORTEX."""

    action_type: str
    utility_score: float = 0.0
    recommendation_confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    recommendation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility_score", max(0.0, min(1.0, self.utility_score)))
        object.__setattr__(
            self,
            "recommendation_confidence",
            max(0.0, min(1.0, self.recommendation_confidence)),
        )


@dataclass(frozen=True, slots=True)
class ReasoningSnapshot:
    """Typed summary of reasoning quality, not model/provider state."""

    reasoning_confidence: float = 1.0
    status: str = "completed"
    contradiction_count: int = 0
    evidence_sufficiency: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reasoning_confidence",
            max(0.0, min(1.0, self.reasoning_confidence)),
        )
        object.__setattr__(
            self,
            "evidence_sufficiency",
            max(0.0, min(1.0, self.evidence_sufficiency)),
        )


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    """Typed semantic policy result consumed by cognition.

    This does not replace Runtime revalidation of authenticated identity, RBAC,
    capability grants, approval requirements, or tenant boundaries.
    """

    decision_id: str | None = None
    blocked_behaviors: tuple[str, ...] = ()
    risk: float = 0.0
    allow_refuse: bool = True
    requires_approval: bool = False
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk", max(0.0, min(1.0, self.risk)))


@dataclass(frozen=True, slots=True)
class MetaSnapshot:
    """Typed self-monitoring result consumed by CORTEX."""

    status: str = "stable"
    meta_confidence: float = 1.0
    recommended_actions: tuple[str, ...] = ()
    verification: VerificationRequirement | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "meta_confidence",
            max(0.0, min(1.0, self.meta_confidence)),
        )


@dataclass(slots=True)
class CognitiveState:
    """Canonical typed state carried between cognitive stages.

    The state contains semantic snapshots and references only. It must never
    contain provider clients, database sessions, HTTP requests, Redis clients,
    tool implementations, or other execution/platform objects.
    """

    request_id: str
    correlation_id: str
    scope: CognitiveScope
    intent: str = "general"
    intent_confidence: float = 0.0
    memory: MemorySignalSnapshot = field(default_factory=MemorySignalSnapshot)
    beliefs: BeliefSnapshot = field(default_factory=BeliefSnapshot)
    goals: GoalSnapshot = field(default_factory=GoalSnapshot)
    salience: SalienceSnapshot = field(default_factory=SalienceSnapshot)
    user_model: UserModelSnapshot = field(default_factory=UserModelSnapshot)
    relationship: RelationshipSnapshot = field(default_factory=RelationshipSnapshot)
    context: ContextSnapshot = field(default_factory=ContextSnapshot)
    reasoning: ReasoningSnapshot = field(default_factory=ReasoningSnapshot)
    meta: MetaSnapshot = field(default_factory=MetaSnapshot)
    adaptive_recommendations: tuple[AdaptiveRecommendationSnapshot, ...] = ()
    policy: PolicySnapshot = field(default_factory=PolicySnapshot)
    capability_requirements: tuple[str, ...] = ()
    schema_version: str = COGNITIVE_SCHEMA_VERSION
    policy_version: str = COGNITIVE_POLICY_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.intent_confidence = max(0.0, min(1.0, self.intent_confidence))


__all__ = [
    "COGNITIVE_POLICY_VERSION",
    "COGNITIVE_SCHEMA_VERSION",
    "AdaptiveRecommendationSnapshot",
    "BeliefSnapshot",
    "CognitiveScope",
    "CognitiveState",
    "ContextSnapshot",
    "GoalSnapshot",
    "MemorySignalSnapshot",
    "MetaSnapshot",
    "PolicySnapshot",
    "ReasoningDepth",
    "ReasoningSnapshot",
    "RelationshipSnapshot",
    "SalienceSnapshot",
    "UserModelSnapshot",
    "VerificationReason",
    "VerificationRequirement",
]
