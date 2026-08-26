from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.contracts.cognitive import SalienceConfidence
from ai_karen_engine.core.contracts.values import JsonMap


class SalienceDimension(str, Enum):
    NOVELTY = "novelty"
    URGENCY = "urgency"
    USER_EMPHASIS = "user_emphasis"
    RELATIONSHIP_IMPORTANCE = "relationship_importance"
    GOAL_RELEVANCE = "goal_relevance"
    RISK = "risk"
    SURPRISE = "surprise"
    REWARD_SIGNIFICANCE = "reward_significance"
    FAILURE_SIGNIFICANCE = "failure_significance"
    SUCCESS_SIGNIFICANCE = "success_significance"
    REPETITION = "repetition"
    UNRESOLVED_STATE = "unresolved_state"
    CONTRADICTION = "contradiction"
    INTERRUPTION_COST = "interruption_cost"


class SalienceReasonCode(str, Enum):
    HIGH_URGENCY = "high_urgency"
    USER_EXPLICIT_EMPHASIS = "user_explicit_emphasis"
    GOAL_CRITICAL = "goal_critical"
    HIGH_RISK = "high_risk"
    PREDICTION_ERROR = "prediction_error"
    UNRESOLVED_COMMITMENT = "unresolved_commitment"
    RELATIONSHIP_RELEVANCE = "relationship_relevance"
    REPEATED_FAILURE = "repeated_failure"
    CONTRADICTION_DETECTED = "contradiction_detected"
    LOW_REPETITION = "low_repetition"
    REWARD_SIGNAL = "reward_signal"
    INTERRUPTION_IMMINENT = "interruption_imminent"


class SalienceSource(str, Enum):
    USER_INPUT = "user_input"
    GOAL_SYSTEM = "goal_system"
    MEMORY_SYSTEM = "memory_system"
    PREDICTION_ERROR = "prediction_error"
    ADAPTIVE_SIGNAL = "adaptive_signal"
    REASONING_ASSESSMENT = "reasoning_assessment"


@dataclass(slots=True)
class SalienceContext:
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    intent: str = "general"
    current_goals: list[str] = field(default_factory=list)
    active_relationships: list[str] = field(default_factory=list)
    recent_predictions: list[JsonMap] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("salience tenant_id must be explicit and non-default")


@dataclass(slots=True)
class SalienceSignal:
    dimension: SalienceDimension
    value: float = 0.0
    confidence: SalienceConfidence = field(default_factory=SalienceConfidence)
    source: SalienceSource = SalienceSource.ADAPTIVE_SIGNAL
    reason_codes: list[SalienceReasonCode] = field(default_factory=list)
    decay_rate: float = 0.1
    retrigger_count: int = 0
    last_activated_at: datetime | None = None
    persistence_class: str = "standard"
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExpectedState:
    description: str
    confidence: float = 0.0
    source_ref: str = ""


@dataclass(slots=True)
class ObservedState:
    description: str
    confidence: float = 0.0
    source_ref: str = ""


@dataclass(slots=True)
class PredictionError:
    expected: ExpectedState
    observed: ObservedState
    error_magnitude: float = 0.0
    dimension_affected: SalienceDimension = SalienceDimension.SURPRISE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserEmphasisSignal:
    emphasis_type: str
    target: str
    strength: float = 0.0
    confidence: SalienceConfidence = field(default_factory=SalienceConfidence)
    source_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RelationshipRelevanceSignal:
    relationship_id: str
    relationship_type: str = "general"
    relevance_strength: float = 0.0
    shared_project: str | None = None
    explicit_commitment: str | None = None
    known_preference_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemorySalienceSignal:
    memory_id: str
    tenant_id: str
    salience_value: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("memory salience tenant_id must be explicit and non-default")


@dataclass(slots=True)
class GoalSalienceAdjustment:
    goal_id: str
    tenant_id: str
    adjustment: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("goal salience tenant_id must be explicit and non-default")


@dataclass(slots=True)
class SalienceAssessment:
    novelty: float = 0.0
    urgency: float = 0.0
    goal_relevance: float = 0.0
    relationship_importance: float = 0.0
    risk: float = 0.0
    surprise: float = 0.0
    reward_significance: float = 0.0
    failure_significance: float = 0.0
    success_significance: float = 0.0
    repetition: float = 0.0
    unresolved_state: float = 0.0
    contradiction: float = 0.0
    interruption_cost: float = 0.0
    user_emphasis: float = 0.0
    overall: float = 0.0
    confidence: SalienceConfidence = field(default_factory=SalienceConfidence)
    reason_codes: list[SalienceReasonCode] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    activation: float = 0.0
    modulation: float = 0.0
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.overall == 0.0:
            self.overall = self._compute_overall()
            self.activation = self._compute_activation()
            self.modulation = max(0.0, min(1.0, 1.0 - self.interruption_cost))

    def _compute_activation(self) -> float:
        dimensions = (
            self.novelty,
            self.urgency,
            self.goal_relevance,
            self.relationship_importance,
            self.risk,
            self.surprise,
            self.reward_significance,
            self.failure_significance,
            self.success_significance,
            self.unresolved_state,
            self.contradiction,
            self.user_emphasis,
            self.repetition,
        )
        return max(0.0, min(1.0, max(dimensions, default=0.0)))

    def _compute_overall(self) -> float:
        activation = self._compute_activation()
        modulation = max(0.0, min(1.0, 1.0 - self.interruption_cost))
        return max(0.0, min(1.0, activation * modulation))


@dataclass(slots=True)
class SalienceAssessmentRequest:
    context: SalienceContext
    signals: list[SalienceSignal] = field(default_factory=list)
    prediction_errors: list[PredictionError] = field(default_factory=list)
    user_emphasis: list[UserEmphasisSignal] = field(default_factory=list)
    relationship_signals: list[RelationshipRelevanceSignal] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SalienceAssessmentResult:
    assessment: SalienceAssessment
    memory_signals: list[MemorySalienceSignal] = field(default_factory=list)
    goal_adjustments: list[GoalSalienceAdjustment] = field(default_factory=list)
    diagnostics: JsonMap = field(default_factory=dict)
    assessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
