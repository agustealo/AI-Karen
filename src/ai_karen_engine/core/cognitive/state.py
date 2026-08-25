"""Typed cognitive state envelope for canonical cognitive boundaries."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class BeliefSnapshot:
    belief_id: str
    confidence: float = 0.0
    consistency: float = 0.0
    source_diversity: float = 0.0
    temporal_validity: str = "unknown"
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
    deadline: str | None = None
    blocked: bool = False
    required_capabilities: list[str] = field(default_factory=list)
    affinity: dict[str, float] = field(default_factory=dict)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SalienceSnapshot:
    assessment_id: str
    overall: float = 0.0
    confidence: float = 0.0
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
    confidence: float = 0.0
    memory_reliability: float = 0.0
    reasoning_confidence: float = 0.0
    evidence_consistency: float = 0.0
    is_looping: bool = False
    calibration_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveSnapshot:
    snapshot_id: str
    utility_score: float = 0.0
    learning_rate: float = 0.0
    adaptation_count: int = 0
    recent_success_rate: float = 0.0
    exploration_bonus: float = 0.0
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicySnapshot:
    policy_id: str
    tenant_id: str = "default"
    blocked_behaviors: list[str] = field(default_factory=list)
    risk_level: float = 0.0
    approval_required: bool = False
    constraints: list[str] = field(default_factory=list)
    policy_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CognitiveState:
    state_id: str
    request_id: str
    correlation_id: str
    tenant_id: str = "default"
    user_id: str | None = None
    session_id: str | None = None
    
    belief: BeliefSnapshot | None = None
    goals: list[GoalSnapshot] = field(default_factory=list)
    salience: SalienceSnapshot | None = None
    context: ContextSnapshot | None = None
    meta: MetaSnapshot | None = None
    adaptive: AdaptiveSnapshot | None = None
    policy: PolicySnapshot | None = None
    
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_complete(self) -> bool:
        required_fields = [self.belief, self.salience, self.context, self.meta]
        return all(field is not None for field in required_fields)

    def get_policy_version(self) -> str:
        return self.policy_version

    def get_schema_version(self) -> str:
        return self.schema_version

    def with_policy_version(self, version: str) -> "CognitiveState":
        return CognitiveState(
            state_id=self.state_id,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            belief=self.belief,
            goals=self.goals,
            salience=self.salience,
            context=self.context,
            meta=self.meta,
            adaptive=self.adaptive,
            policy=self.policy,
            policy_version=version,
            schema_version=self.schema_version,
            created_at=self.created_at,
            metadata=self.metadata.copy(),
        )