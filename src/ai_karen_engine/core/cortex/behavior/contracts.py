from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


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
    """Configuration for cognitive policy versioning."""
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scoring_version: str = "1.0.0"
    meta_version: str = "1.0.0"
    salience_version: str = "1.0.0"


class VerificationReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    HIGH_RISK = "high_risk"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_MEMORY = "stale_memory"
    EXTERNAL_FACT = "external_fact"
    FAILED_PREVIOUS_STRATEGY = "failed_previous_strategy"


class VerificationDepth(str, Enum):
    NONE = "none"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(slots=True)
class BehaviorCandidate:
    """A candidate behavior for selection."""
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


@dataclass(slots=True)
class BehaviorSelectionContext:
    """Semantic snapshot for behavior selection. No provider/session objects."""
    request_id: str
    correlation_id: str
    tenant_id: str = "default"
    user_id: str | None = None
    session_id: str | None = None
    intent: str = "general"
    intent_confidence: float = 0.0
    belief_assessment: dict[str, Any] = field(default_factory=dict)
    goal_state: dict[str, Any] = field(default_factory=dict)
    context_plan: dict[str, Any] = field(default_factory=dict)
    salience: dict[str, Any] = field(default_factory=dict)
    memory_signals: list[dict[str, Any]] = field(default_factory=list)
    user_model: dict[str, Any] = field(default_factory=dict)
    relationship_context: dict[str, Any] = field(default_factory=dict)
    adaptive_recommendations: list[dict[str, Any]] = field(default_factory=list)
    reasoning_assessment: dict[str, Any] = field(default_factory=dict)
    policy_constraints: dict[str, Any] = field(default_factory=dict)
    capability_requirements: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CognitivePolicyConfig:
    """Configuration for cognitive policy versioning."""
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scoring_version: str = "1.0.0"
    meta_version: str = "1.0.0"
    salience_version: str = "1.0.0"


@dataclass(slots=True)
class BehaviorScoreComponents:
    """Explainable score components for a behavior."""
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
    weights: dict[str, float] = field(default_factory=lambda: {
        "goal_alignment": 0.15,
        "belief_support": 0.15,
        "salience_fit": 0.12,
        "user_preference_fit": 0.10,
        "historical_success": 0.08,
        "policy_fit": 0.20,
        "confidence": 0.10,
        "verification_value": 0.05,
        "capability_fit": 0.05,
    })
    policy_version: str = "1.0.0"

    @property
    def utility(self) -> float:
        if self.policy_fit == 0.0:
            return 0.0
        
        weighted_sum = (
            self.goal_alignment * self.weights.get("goal_alignment", 0.15) +
            self.belief_support * self.weights.get("belief_support", 0.15) +
            self.salience_fit * self.weights.get("salience_fit", 0.12) +
            self.user_preference_fit * self.weights.get("user_preference_fit", 0.10) +
            self.historical_success * self.weights.get("historical_success", 0.08) +
            self.policy_fit * self.weights.get("policy_fit", 0.20) +
            self.confidence * self.weights.get("confidence", 0.10) +
            self.verification_value * self.weights.get("verification_value", 0.05) +
            self.capability_fit * self.weights.get("capability_fit", 0.05)
        )
        penalties = self.risk + self.interruption_cost
        return max(0.0, min(1.0, weighted_sum - penalties))


@dataclass(slots=True)
class VerificationRequirement:
    """Structured verification decision."""
    required: bool = False
    reason: VerificationReason | None = None
    depth: VerificationDepth = VerificationDepth.STANDARD
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BehaviorDecision:
    final behavior decision from CORTEX. Never execution instructions."""
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
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
