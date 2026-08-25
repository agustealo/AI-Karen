from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from ai_karen_engine.core.contracts.cognitive import (
    AdaptiveRecommendationSnapshot,
    BeliefSnapshot,
    ContextSnapshot,
    GoalSnapshot,
    MemorySignalSnapshot,
    PolicySnapshot,
    ReasoningDepth,
    ReasoningSnapshot,
    RelationshipSnapshot,
    SalienceSnapshot,
    UserModelSnapshot,
    VerificationReason,
    VerificationRequirement,
)

# Compatibility alias only. Canonical type is ReasoningDepth.
# Sunset: remove after callers migrate from VerificationDepth imports.
VerificationDepth = ReasoningDepth


class BehaviorType(str, Enum):
    RESPOND = "respond"
    REASON = "reason"
    RECALL = "recall"
    VERIFY = "verify"
    ASK = "ask"
    USE_CAPABILITY = "use_capability"
    USE_WORKFLOW = "use_workflow"
    DELEGATE = "delegate"
    WAIT = "wait"
    DEFER = "defer"
    SUGGEST = "suggest"
    REFUSE = "refuse"
    ABSTAIN = "abstain"
    NO_ACTION = "no_action"


class BehaviorTarget(str, Enum):
    USER = "user"
    SYSTEM = "system"
    CAPABILITY = "capability"
    WORKFLOW = "workflow"
    AGENT = "agent"
    MEMORY = "memory"
    REASONING = "reasoning"


class BehaviorSource(str, Enum):
    CORTEX_DECISION = "cortex_decision"
    ADAPTIVE_RECOMMENDATION = "adaptive_recommendation"
    GOAL_SIGNAL = "goal_signal"
    MEMORY_SIGNAL = "memory_signal"
    POLICY_GATE = "policy_gate"
    REASONING_ASSESSMENT = "reasoning_assessment"
    SALIENCE = "salience"


class BehaviorConstraint(str, Enum):
    REQUIRES_VERIFICATION = "requires_verification"
    REQUIRES_APPROVAL = "requires_approval"
    POLICY_BLOCKED = "policy_blocked"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    TENANT_RESTRICTED = "tenant_restricted"
    DEGRADED = "degraded"
    HIGH_RISK = "high_risk"


@dataclass(slots=True)
class CognitivePolicyConfig:
    """Version identifiers attached to behavior decisions."""

    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scoring_version: str = "1.0.0"


@dataclass(slots=True)
class BehaviorCandidate:
    """A candidate behavior for CORTEX selection."""

    candidate_id: str
    behavior_type: BehaviorType
    target: BehaviorTarget | None = None
    target_id: str | None = None
    source: BehaviorSource = BehaviorSource.CORTEX_DECISION
    score: float = 0.0
    confidence: float = 0.0
    constraints: list[BehaviorConstraint] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    goal_refs: list[str] = field(default_factory=list)
    belief_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _belief_snapshot(value: BeliefSnapshot | Mapping[str, Any]) -> BeliefSnapshot:
    if isinstance(value, BeliefSnapshot):
        return value
    return BeliefSnapshot(
        active_claim_ids=tuple(value.get("active_claim_ids", ())),
        disputed_claim_ids=tuple(value.get("disputed_claim_ids", ())),
        epistemic_confidence=float(value.get("epistemic_confidence", value.get("confidence", 1.0))),
        contradiction_count=int(value.get("contradiction_count", 0)),
        stale=bool(value.get("stale", False)),
        evidence_refs=tuple(value.get("evidence_refs", ())),
    )


def _goal_snapshot(value: GoalSnapshot | Mapping[str, Any]) -> GoalSnapshot:
    if isinstance(value, GoalSnapshot):
        return value
    return GoalSnapshot(
        active_goal_ids=tuple(value.get("active_goal_ids", value.get("active_goals", ()))),
        blocked_goal_ids=tuple(value.get("blocked_goal_ids", ())),
        ready_intention_ids=tuple(value.get("ready_intention_ids", ())),
        open_commitment_ids=tuple(value.get("open_commitment_ids", ())),
        priority_by_goal=tuple(value.get("priority_by_goal", ())),
    )


def _context_snapshot(value: ContextSnapshot | Mapping[str, Any]) -> ContextSnapshot:
    if isinstance(value, ContextSnapshot):
        return value
    return ContextSnapshot(
        selected_ids=tuple(value.get("selected_ids", value.get("included_ids", ()))),
        omitted_ids=tuple(value.get("omitted_ids", ())),
        conflict_ids=tuple(value.get("conflict_ids", ())),
        token_budget=int(value.get("token_budget", 0)),
        estimated_tokens_used=int(value.get("estimated_tokens_used", 0)),
        complete=bool(value.get("complete", True)),
    )


def _salience_snapshot(value: SalienceSnapshot | Mapping[str, Any]) -> SalienceSnapshot:
    if isinstance(value, SalienceSnapshot):
        return value
    return SalienceSnapshot(
        overall=float(value.get("overall", 0.0)),
        activation=float(value.get("activation", value.get("overall", 0.0))),
        inhibition=float(value.get("inhibition", 0.0)),
        salience_confidence=float(value.get("salience_confidence", value.get("confidence", 0.0))),
        dominant_dimensions=tuple(value.get("dominant_dimensions", ())),
        source_refs=tuple(value.get("source_refs", ())),
    )


def _memory_snapshot(value: MemorySignalSnapshot | Mapping[str, Any] | list[Mapping[str, Any]]) -> MemorySignalSnapshot:
    if isinstance(value, MemorySignalSnapshot):
        return value
    if isinstance(value, list):
        ids = tuple(str(item.get("memory_id", "")) for item in value if item.get("memory_id"))
        confidence = max((float(item.get("confidence", item.get("salience_value", 0.0))) for item in value), default=0.0)
        return MemorySignalSnapshot(memory_ids=ids, retrieval_confidence=confidence)
    return MemorySignalSnapshot(
        memory_ids=tuple(value.get("memory_ids", ())),
        retrieval_confidence=float(value.get("retrieval_confidence", value.get("confidence", 0.0))),
        degraded=bool(value.get("degraded", False)),
        degradation_reason=value.get("degradation_reason"),
    )


def _user_snapshot(value: UserModelSnapshot | Mapping[str, Any]) -> UserModelSnapshot:
    if isinstance(value, UserModelSnapshot):
        return value
    return UserModelSnapshot(
        prefers_action_over_clarification=bool(value.get("prefers_action_over_clarification", True)),
        explicit_preference_refs=tuple(value.get("explicit_preference_refs", ())),
        inferred_preference_refs=tuple(value.get("inferred_preference_refs", ())),
    )


def _relationship_snapshot(value: RelationshipSnapshot | Mapping[str, Any]) -> RelationshipSnapshot:
    if isinstance(value, RelationshipSnapshot):
        return value
    return RelationshipSnapshot(
        relationship_ids=tuple(value.get("relationship_ids", ())),
        shared_project_refs=tuple(value.get("shared_project_refs", value.get("shared_projects", ()))),
        unresolved_thread_refs=tuple(value.get("unresolved_thread_refs", value.get("unresolved_threads", ()))),
    )


def _adaptive_snapshots(
    value: tuple[AdaptiveRecommendationSnapshot, ...] | list[AdaptiveRecommendationSnapshot] | list[Mapping[str, Any]],
) -> tuple[AdaptiveRecommendationSnapshot, ...]:
    result: list[AdaptiveRecommendationSnapshot] = []
    for item in value:
        if isinstance(item, AdaptiveRecommendationSnapshot):
            result.append(item)
        else:
            result.append(
                AdaptiveRecommendationSnapshot(
                    action_type=str(item.get("action_type", "")),
                    utility_score=float(item.get("utility_score", 0.0)),
                    recommendation_confidence=float(item.get("recommendation_confidence", item.get("confidence", 0.0))),
                    reason_codes=tuple(item.get("reason_codes", ())),
                    recommendation_id=item.get("recommendation_id"),
                )
            )
    return tuple(result)


def _reasoning_snapshot(value: ReasoningSnapshot | Mapping[str, Any]) -> ReasoningSnapshot:
    if isinstance(value, ReasoningSnapshot):
        return value
    return ReasoningSnapshot(
        reasoning_confidence=float(value.get("reasoning_confidence", value.get("confidence", 1.0))),
        status=str(value.get("status", "completed")),
        contradiction_count=int(value.get("contradiction_count", 0)),
        evidence_sufficiency=float(value.get("evidence_sufficiency", 1.0)),
    )


def _policy_snapshot(value: PolicySnapshot | Mapping[str, Any]) -> PolicySnapshot:
    if isinstance(value, PolicySnapshot):
        return value
    return PolicySnapshot(
        decision_id=value.get("decision_id"),
        blocked_behaviors=tuple(value.get("blocked_behaviors", ())),
        risk=float(value.get("risk", 0.0)),
        allow_refuse=bool(value.get("allow_refuse", True)),
        requires_approval=bool(value.get("requires_approval", False)),
        reason_codes=tuple(value.get("reason_codes", ())),
    )


@dataclass(slots=True)
class BehaviorSelectionContext:
    """Typed semantic snapshot for behavior selection.

    Legacy mappings are accepted only at construction and immediately coerced
    into typed snapshots. Public fields remain typed to prevent schema drift.
    Tenant scope is explicit; "default" is not an acceptable security scope.
    """

    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    intent: str = "general"
    intent_confidence: float = 0.0
    belief_assessment: BeliefSnapshot | Mapping[str, Any] = field(default_factory=BeliefSnapshot)
    goal_state: GoalSnapshot | Mapping[str, Any] = field(default_factory=GoalSnapshot)
    context_plan: ContextSnapshot | Mapping[str, Any] = field(default_factory=ContextSnapshot)
    salience: SalienceSnapshot | Mapping[str, Any] = field(default_factory=SalienceSnapshot)
    memory_signals: MemorySignalSnapshot | Mapping[str, Any] | list[Mapping[str, Any]] = field(default_factory=MemorySignalSnapshot)
    user_model: UserModelSnapshot | Mapping[str, Any] = field(default_factory=UserModelSnapshot)
    relationship_context: RelationshipSnapshot | Mapping[str, Any] = field(default_factory=RelationshipSnapshot)
    adaptive_recommendations: tuple[AdaptiveRecommendationSnapshot, ...] | list[AdaptiveRecommendationSnapshot] | list[Mapping[str, Any]] = ()
    reasoning_assessment: ReasoningSnapshot | Mapping[str, Any] = field(default_factory=ReasoningSnapshot)
    policy_constraints: PolicySnapshot | Mapping[str, Any] = field(default_factory=PolicySnapshot)
    capability_requirements: tuple[str, ...] | list[str] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("BehaviorSelectionContext requires an explicit tenant_id")
        self.intent_confidence = max(0.0, min(1.0, self.intent_confidence))
        self.belief_assessment = _belief_snapshot(self.belief_assessment)
        self.goal_state = _goal_snapshot(self.goal_state)
        self.context_plan = _context_snapshot(self.context_plan)
        self.salience = _salience_snapshot(self.salience)
        self.memory_signals = _memory_snapshot(self.memory_signals)
        self.user_model = _user_snapshot(self.user_model)
        self.relationship_context = _relationship_snapshot(self.relationship_context)
        self.adaptive_recommendations = _adaptive_snapshots(self.adaptive_recommendations)
        self.reasoning_assessment = _reasoning_snapshot(self.reasoning_assessment)
        self.policy_constraints = _policy_snapshot(self.policy_constraints)
        self.capability_requirements = tuple(self.capability_requirements)


@dataclass(slots=True)
class BehaviorScoreComponents:
    """Explainable, weighted score components for a behavior."""

    goal_alignment: float = 0.0
    belief_support: float = 0.0
    salience_fit: float = 0.0
    user_preference_fit: float = 0.0
    historical_success: float = 0.0
    risk: float = 0.0
    policy_fit: float = 0.0
    confidence: float = 0.0
    interruption_cost: float = 0.0
    verification_value: float = 0.0
    capability_fit: float = 0.0
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "goal_alignment": 0.15,
            "belief_support": 0.15,
            "salience_fit": 0.12,
            "user_preference_fit": 0.10,
            "historical_success": 0.08,
            "policy_fit": 0.20,
            "confidence": 0.10,
            "verification_value": 0.05,
            "capability_fit": 0.05,
        }
    )
    policy_version: str = "1.0.0"

    @property
    def utility(self) -> float:
        if self.policy_fit <= 0.0:
            return 0.0
        weighted_sum = (
            self.goal_alignment * self.weights["goal_alignment"]
            + self.belief_support * self.weights["belief_support"]
            + self.salience_fit * self.weights["salience_fit"]
            + self.user_preference_fit * self.weights["user_preference_fit"]
            + self.historical_success * self.weights["historical_success"]
            + self.policy_fit * self.weights["policy_fit"]
            + self.confidence * self.weights["confidence"]
            + self.verification_value * self.weights["verification_value"]
            + self.capability_fit * self.weights["capability_fit"]
        )
        return max(0.0, min(1.0, weighted_sum - self.risk - self.interruption_cost))


@dataclass(slots=True)
class BehaviorDecision:
    """Final behavior decision from CORTEX. Never execution instructions."""

    decision_id: str
    selected_behavior: BehaviorType
    alternatives: list[BehaviorCandidate] = field(default_factory=list)
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    goal_refs: list[str] = field(default_factory=list)
    belief_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    policy_decision_ref: str | None = None
    requires_verification: VerificationRequirement | None = None
    requires_approval: bool = False
    degraded: bool = False
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scoring_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


__all__ = [
    "BehaviorCandidate",
    "BehaviorConstraint",
    "BehaviorDecision",
    "BehaviorScoreComponents",
    "BehaviorSelectionContext",
    "BehaviorSource",
    "BehaviorTarget",
    "BehaviorType",
    "CognitivePolicyConfig",
    "ReasoningDepth",
    "VerificationDepth",
    "VerificationReason",
    "VerificationRequirement",
]
