from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.contracts.values import JsonMap


class LearningSignalType(str, Enum):
    POSITIVE_OUTCOME = "positive_outcome"
    NEGATIVE_OUTCOME = "negative_outcome"
    USER_CORRECTION = "user_correction"
    USER_ACCEPTANCE = "user_acceptance"
    USER_REJECTION = "user_rejection"
    STRATEGY_SUCCESS = "strategy_success"
    STRATEGY_FAILURE = "strategy_failure"
    CAPABILITY_SUCCESS = "capability_success"
    CAPABILITY_FAILURE = "capability_failure"
    MEMORY_HELPFUL = "memory_helpful"
    MEMORY_MISLEADING = "memory_misleading"
    VERIFICATION_CAUGHT_ERROR = "verification_caught_error"
    CLARIFICATION_HELPFUL = "clarification_helpful"
    CLARIFICATION_UNNECESSARY = "clarification_unnecessary"


class LearningStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class LearningScope(str, Enum):
    GLOBAL = "global"
    USER = "user"
    TENANT = "tenant"
    TASK_TYPE = "task_type"
    DOMAIN = "domain"
    PROJECT = "project"
    CAPABILITY = "capability"
    AGENT = "agent"
    STRATEGY = "strategy"


class OutcomeAssessmentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    ABORTED = "aborted"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class LearningFailureClass(str, Enum):
    BAD_REASONING = "bad_reasoning"
    BAD_MEMORY = "bad_memory"
    BAD_CONTEXT = "bad_context"
    WRONG_CAPABILITY = "wrong_capability"
    WRONG_PROVIDER_TARGET = "wrong_provider_target"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNNECESSARY_CLARIFICATION = "unnecessary_clarification"
    FAILED_VERIFICATION = "failed_verification"
    POLICY_BLOCK = "policy_block"
    RUNTIME_FAILURE = "runtime_failure"


class LearningEligibility(str, Enum):
    IGNORE = "ignore"
    RECORD_ONLY = "record_only"
    REFLECT = "reflect"
    UPDATE_PROFILE = "update_profile"
    CANDIDATE_FOR_CONSOLIDATION = "candidate_for_consolidation"
    CANDIDATE_FOR_MODEL_TRAINING = "candidate_for_model_training"


@dataclass(slots=True)
class ExperienceObservation:
    """Semantic observation of an experience. No raw provider logs."""

    observation_id: str
    what_was_tried: str
    why_chosen: str
    task_signature_ref: dict[str, Any] = field(default_factory=dict)
    goal_refs: list[str] = field(default_factory=list)
    belief_refs: list[str] = field(default_factory=list)
    behavior_decision_ref: str | None = None
    expected_outcome: JsonMap = field(default_factory=dict)
    actual_outcome: JsonMap = field(default_factory=dict)
    user_feedback: str | None = None
    verification_result: str | None = None
    tenant_id: str = "default"
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class OutcomeAssessment:
    """Normalized assessment of an outcome."""

    status: OutcomeAssessmentStatus = OutcomeAssessmentStatus.UNKNOWN
    task_completion: float = 0.0
    correctness: float = 0.0
    user_acceptance: float = 0.0
    correction_needed: bool = False
    efficiency: float = 0.0
    safety: float = 0.0
    policy_compliance: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningSignal:
    """Derived learning signal from an experience."""

    signal_id: str
    signal_type: LearningSignalType
    strength: LearningStrength = LearningStrength.MODERATE
    scope: LearningScope = LearningScope.USER
    source_experience_id: str = ""
    related_capability: str | None = None
    related_agent: str | None = None
    related_strategy: str | None = None
    sample_count: int = 1
    explicit_feedback: bool = False
    outcome_confidence: float = 0.0
    source_diversity: float = 0.0
    repeatability: float = 0.0
    context_similarity: float = 0.0
    contradiction_count: int = 0
    tenant_id: str = "default"
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class LearningRewardVector:
    """Multi-dimensional reward vector."""

    task_success: float = 0.0
    user_satisfaction: float = 0.0
    correctness: float = 0.0
    efficiency: float = 0.0
    safety: float = 0.0
    cost: float = 0.0
    latency: float = 0.0
    clarification_cost: float = 0.0
    verification_value: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def aggregate(self) -> float:
        raw = (
            self.task_success
            + self.user_satisfaction
            + self.correctness
            + self.efficiency
            + self.safety
            + self.verification_value
        )
        penalties = self.cost + self.latency + self.clarification_cost
        return max(0.0, min(1.0, raw - penalties))


@dataclass(slots=True)
class LearningFailureClassification:
    """Classification of learning failure."""

    failure_class: LearningFailureClass
    description: str = ""
    recoverable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutcomeAttribution:
    """Attribution of outcome to contributing factors with uncertainty."""

    memory_contribution: float = 0.0
    reasoning_strategy_contribution: float = 0.0
    capability_contribution: float = 0.0
    user_clarification_contribution: float = 0.0
    verification_contribution: float = 0.0
    workflow_contribution: float = 0.0
    fallback_contribution: float = 0.0
    uncertainty: float = 0.0
    primary_driver: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningEligibilityDecision:
    """Eligibility decision for an experience."""

    action: LearningEligibility = LearningEligibility.IGNORE
    reason: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReflectionTrigger:
    """Trigger for reflection based on experience."""

    trigger_id: str
    trigger_type: str
    experience_ids: list[str] = field(default_factory=list)
    urgency: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProfileUpdateCandidate:
    """Candidate update for adaptive performance profiles."""

    candidate_id: str
    profile_type: str
    target_id: str
    proposed_changes: JsonMap = field(default_factory=dict)
    confidence: float = 0.0
    scope: LearningScope = LearningScope.USER
    tenant_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExperienceToLearningRequest:
    """Request to convert experiences to learning signals."""

    request_id: str
    correlation_id: str
    experiences: list[ExperienceObservation] = field(default_factory=list)
    outcome_assessments: list[OutcomeAssessment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExperienceToLearningResult:
    """Result of converting experiences to learning signals."""

    signals: list[LearningSignal] = field(default_factory=list)
    reward_vector: LearningRewardVector | None = None
    attributions: list[OutcomeAttribution] = field(default_factory=list)
    eligibility: LearningEligibilityDecision | None = None
    reflection_triggers: list[ReflectionTrigger] = field(default_factory=list)
    profile_updates: list[ProfileUpdateCandidate] = field(default_factory=list)
    diagnostics: JsonMap = field(default_factory=dict)
    processed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
