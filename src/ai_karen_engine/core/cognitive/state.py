"""Typed cognitive state envelope for canonical cognitive boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.contracts.cognitive import (
    BehaviorConfidence,
    EpistemicConfidence,
    LearningConfidence,
    MetaConfidence,
    RetrievalConfidence,
    SalienceConfidence,
)


@dataclass(slots=True)
class BeliefSnapshot:
    belief_id: str
    confidence: EpistemicConfidence = field(default_factory=EpistemicConfidence)
    consistency: float = 0.0
    source_diversity: float = 0.0
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_verified_at: datetime | None = None
    contradictions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GoalSnapshot:
    goal_id: str
    state: str = "unknown"
    priority: float = 0.0
    progress: float = 0.0
    deadline: datetime | None = None
    blocked: bool = False
    required_capabilities: list[str] = field(default_factory=list)
    affinity: dict[str, float] = field(default_factory=dict)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SalienceSnapshot:
    assessment_id: str
    overall: float = 0.0
    confidence: SalienceConfidence = field(default_factory=SalienceConfidence)
    dimensions: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    activation: float = 0.0
    modulation: float = 0.0
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextSnapshot:
    plan_id: str
    selected_count: int = 0
    omitted_count: int = 0
    token_usage: int = 0
    priority_distribution: dict[str, int] = field(default_factory=dict)
    conflicts_resolved: int = 0
    budget_remaining: dict[str, int] = field(default_factory=dict)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetaSnapshot:
    assessment_id: str
    status: str = "stable"
    confidence: MetaConfidence = field(default_factory=MetaConfidence)
    memory_reliability: RetrievalConfidence = field(default_factory=RetrievalConfidence)
    reasoning_confidence: float = 0.0
    evidence_consistency: float = 0.0
    is_looping: bool = False
    calibration_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveRecommendationSnapshot:
    action_type: str
    utility_score: float = 0.0
    confidence: LearningConfidence = field(default_factory=LearningConfidence)
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdaptiveSnapshot:
    snapshot_id: str
    utility_score: float = 0.0
    learning_rate: float = 0.0
    adaptation_count: int = 0
    recent_success_rate: float = 0.0
    exploration_bonus: float = 0.0
    recommendations: list[AdaptiveRecommendationSnapshot] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicySnapshot:
    policy_id: str
    tenant_id: str
    blocked_behaviors: list[str] = field(default_factory=list)
    risk_level: float = 0.0
    approval_required: bool = False
    constraints: list[str] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("policy tenant_id must be explicit and non-default")


@dataclass(slots=True)
class CognitiveState:
    """Canonical typed state passed between cognitive stages."""

    state_id: str
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    belief: BeliefSnapshot | None = None
    goals: list[GoalSnapshot] = field(default_factory=list)
    salience: SalienceSnapshot | None = None
    context: ContextSnapshot | None = None
    meta: MetaSnapshot | None = None
    adaptive: AdaptiveSnapshot | None = None
    policy: PolicySnapshot | None = None
    behavior_confidence: BehaviorConfidence = field(default_factory=BehaviorConfidence)
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("cognitive tenant_id must be explicit and non-default")

    def is_complete(self) -> bool:
        required_fields = [self.belief, self.salience, self.context, self.meta]
        return all(value is not None for value in required_fields)

    def with_policy_version(self, version: str) -> "CognitiveState":
        return CognitiveState(
            state_id=self.state_id,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            conversation_id=self.conversation_id,
            project_id=self.project_id,
            belief=self.belief,
            goals=list(self.goals),
            salience=self.salience,
            context=self.context,
            meta=self.meta,
            adaptive=self.adaptive,
            policy=self.policy,
            behavior_confidence=self.behavior_confidence,
            policy_version=version,
            schema_version=self.schema_version,
            created_at=self.created_at,
            metadata=self.metadata.copy(),
        )


__all__ = [
    "AdaptiveRecommendationSnapshot",
    "AdaptiveSnapshot",
    "BeliefSnapshot",
    "CognitiveState",
    "ContextSnapshot",
    "GoalSnapshot",
    "MetaSnapshot",
    "PolicySnapshot",
    "SalienceSnapshot",
]
