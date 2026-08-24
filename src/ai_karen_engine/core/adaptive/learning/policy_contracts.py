"""Policy contracts for counterfactual evaluation and safe promotion.

Defines the canonical data structures and protocol interfaces used by the
adaptive policy evaluation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import numpy as np


class ActionRiskClass(str, Enum):
    """Risk classification for policy actions."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    FORBIDDEN = "forbidden"


class DecisionType(str, Enum):
    """Canonical decision types for policy evaluation."""

    PROVIDER_SELECTION = "provider_selection"
    MODEL_SELECTION = "model_selection"
    AGENT_SELECTION = "agent_selection"
    TOOL_SELECTION = "tool_selection"
    MEMORY_SELECTION = "memory_selection"
    WORKFLOW_SELECTION = "workflow_selection"
    RESPOND_STRATEGY = "respond_strategy"


class PolicyStatus(str, Enum):
    """Lifecycle status for policies."""

    CANDIDATE = "candidate"
    SHADOW = "shadow"
    ACTIVE = "active"
    RETIRED = "retired"


class PromotionDecision(str, Enum):
    """Promotion recommendation outcome."""

    PROMOTION_ELIGIBLE = "promotion_eligible"
    PROMOTION_BLOCKED = "promotion_blocked"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DRIFT_BLOCKED = "drift_blocked"
    SAFETY_BLOCKED = "safety_blocked"
    OPE_INELIGIBLE = "ope_ineligible"


class PromotionBlockReason(str, Enum):
    """Explicit reason codes for promotion blocking."""

    INSUFFICIENT_SAMPLES = "insufficient_samples"
    POOR_OVERLAP = "poor_overlap"
    UNSUPPORTED_ACTIONS = "unsupported_actions"
    ESTIMATOR_DISAGREEMENT = "estimator_disagreement"
    SEGMENT_REGRESSION = "segment_regression"
    DRIFT_DETECTED = "drift_detected"
    SAFETY_REVIEW_REQUIRED = "safety_review_required"
    HIGH_RISK_EXPLORATION = "high_risk_exploration"
    CONFIDENCE_TOO_LOW = "confidence_too_low"
    LATENCY_REGRESSION = "latency_regression"
    COST_REGRESSION = "cost_regression"
    FALLBACK_REGRESSION = "fallback_regression"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class OPEIneligibilityReason(str, Enum):
    """Reason codes for OPE ineligibility."""

    MISSING_PROPENSITY = "missing_propensity"
    INVALID_PROPENSITY = "invalid_propensity"
    MISSING_REWARD = "missing_reward"
    UNKNOWN_CHOSEN_ACTION = "unknown_chosen_action"
    MISSING_CONTEXT = "missing_context"
    EMPTY_ACTIONS = "empty_actions"


@dataclass(slots=True)
class PolicyContext:
    """Neutral decision context for policy evaluation.

    Contains only derived/neutral data. No raw runtime objects.
    """

    feature_snapshot_id: str
    decision_type: DecisionType
    normalized_features: dict[str, Any] = field(default_factory=dict)
    eligible_actions: list[str] = field(default_factory=list)
    risk_class: ActionRiskClass = ActionRiskClass.LOW
    tenant_scope: str = "default"
    segment_labels: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    """Result of scoring actions with a policy."""

    scores: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)
    chosen_action: str = ""
    chosen_probability: float = 0.0
    policy_id: str = ""
    policy_version: str = ""
    exploration_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextualPolicy(Protocol):
    """Protocol for versioned contextual policies."""

    policy_id: str
    policy_version: str

    def score_actions(
        self,
        context: PolicyContext,
        eligible_actions: list[str],
    ) -> PolicyDecision:
        ...


@dataclass(slots=True)
class PolicyObservation:
    """Logged decision observation for OPE."""

    observation_id: str
    context: PolicyContext
    eligible_actions: list[str]
    chosen_action: str
    behavior_policy_id: str
    behavior_policy_version: str
    behavior_probabilities: dict[str, float]
    chosen_probability: float
    reward: float
    utility_components: dict[str, float] = field(default_factory=dict)
    utility_policy_version: str = ""
    candidate_probabilities: dict[str, float] = field(default_factory=dict)
    candidate_policy_id: str = ""
    candidate_policy_version: str = ""
    segment_labels: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyEstimate:
    """Estimate from an OPE estimator."""

    estimator_name: str
    estimate: float
    lower_bound: float
    upper_bound: float
    confidence_level: float
    sample_count: int
    effective_sample_size: float
    clipped_weight_count: int = 0
    clipped_weight_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OverlapDiagnostics:
    """Diagnostics for propensity overlap quality."""

    effective_sample_size: float
    minimum_propensity: float
    maximum_importance_weight: float
    coverage: float
    action_support: dict[str, int] = field(default_factory=dict)
    is_supported: bool = True
    unsupported_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UtilityComponents:
    """Decomposed utility components for an outcome."""

    quality: float = 0.0
    success: float = 0.0
    latency: float = 0.0
    fallback_penalty: float = 0.0
    cost: float = 0.0
    user_feedback: float = 0.0
    verification_success: float = 0.0
    safety_penalty: float = 0.0
    components: dict[str, float] = field(default_factory=dict)

    def to_scalar(self, weights: dict[str, float]) -> float:
        raw = (
            weights.get("quality", 0.0) * self.quality
            + weights.get("success", 0.0) * self.success
            + weights.get("user_feedback", 0.0) * self.user_feedback
            + weights.get("verification_success", 0.0) * self.verification_success
            - weights.get("latency", 0.0) * self.latency
            - weights.get("fallback_penalty", 0.0) * self.fallback_penalty
            - weights.get("cost", 0.0) * self.cost
            - weights.get("safety_penalty", 0.0) * self.safety_penalty
        )
        return float(np.clip(raw, 0.0, 1.0))


@dataclass(slots=True)
class UtilityPolicy:
    """Versioned utility policy configuration."""

    utility_policy_id: str = "runtime_quality_v1"
    utility_policy_version: str = "v1"
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "quality": 0.25,
            "success": 0.25,
            "user_feedback": 0.15,
            "verification_success": 0.10,
            "latency": 0.10,
            "fallback_penalty": 0.10,
            "cost": 0.05,
            "safety_penalty": 0.10,
        }
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DerivedUtilityRecord:
    """Derived utility artifact from raw outcome."""

    record_id: str
    utility_policy_version: str
    source_outcome_ids: list[str]
    components: UtilityComponents
    scalar_utility: float
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_probability_distribution(
    probabilities: dict[str, float],
    eligible_actions: list[str],
    tolerance: float = 1e-6,
) -> str | None:
    if not probabilities:
        return "empty_probabilities"
    for action in eligible_actions:
        if action not in probabilities:
            return f"missing_action:{action}"
        p = probabilities[action]
        if np.isnan(p) or np.isinf(p) or p < 0.0:
            return f"invalid_probability:{action}"
    total = sum(probabilities.get(a, 0.0) for a in eligible_actions)
    if abs(total - 1.0) > tolerance:
        return f"invalid_total:{total}"
    return None
