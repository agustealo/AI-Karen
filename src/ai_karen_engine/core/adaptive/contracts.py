"""Adaptive intelligence contracts.

Adaptive remains advisory. These contracts contain semantic recommendations and
outcome summaries only; they never authorize or execute actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.contracts.values import JsonMap


class AdaptiveActionType(str, Enum):
    RESPOND_DIRECTLY = "respond_directly"
    ASK_CLARIFICATION = "ask_clarification"
    RETRIEVE_MEMORY = "retrieve_memory"
    USE_TOOL = "use_tool"
    USE_WORKFLOW = "use_workflow"
    USE_AGENT = "use_agent"
    USE_MULTI_AGENT = "use_multi_agent"
    SUGGEST_ACTION = "suggest_action"
    DO_NOTHING = "do_nothing"


class RecommendationReasonCode(str, Enum):
    HIGH_TASK_FIT = "high_task_fit"
    USER_PREFERS_LOCAL = "user_prefers_local"
    HISTORICAL_SUCCESS_HIGH = "historical_success_high"
    TOOL_UNAVAILABLE = "tool_unavailable"
    HIGH_VERIFICATION_VALUE = "high_verification_value"
    LOW_SAMPLE_CONFIDENCE = "low_sample_confidence"
    HIGH_RISK = "high_risk"
    PRIVACY_RESTRICTION = "privacy_restriction"
    COLD_START = "cold_start"
    CLARIFICATION_NEEDED = "clarification_needed"
    MEMORY_RELEVANCE = "memory_relevance"
    WORKFLOW_BENEFIT = "workflow_benefit"
    MULTI_AGENT_VALUE = "multi_agent_value"
    LATENCY_PENALTY = "latency_penalty"
    COST_PENALTY = "cost_penalty"
    DEFAULT_BASELINE = "default_baseline"


class SuggestionType(str, Enum):
    WORKFLOW_AUTOMATION = "workflow_automation"
    FOLLOW_UP = "follow_up"
    PREFERENCE_LEARNED = "preference_learned"
    CAPABILITY_AVAILABLE = "capability_available"
    MEMORY_CONTINUATION = "memory_continuation"
    EFFICIENCY_TIP = "efficiency_tip"


class SuggestionFeedbackType(str, Enum):
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    ACTED_ON = "acted_on"
    CORRECTED = "corrected"


class CandidateFilterResult(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    REQUIRES_POLICY_VALIDATION = "requires_policy_validation"


def _validate_tenant(value: str | None, owner: str) -> None:
    if not value or value == "default":
        raise ValueError(f"{owner} tenant_id must be explicit and non-default")


@dataclass(slots=True)
class UserStateSnapshot:
    user_id: str
    tenant_id: str | None = None
    session_id: str | None = None
    explicit_preferences: JsonMap = field(default_factory=dict)
    locality_preference: str = "any"
    clarification_tolerance: float = 0.5
    verification_preference: str = "standard"
    interruption_sensitivity: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_tenant(self.tenant_id, "adaptive user state")


@dataclass(slots=True)
class ResolvedPreferences:
    model_locality: str = "any"
    prefers_local: bool = False
    prefers_action_over_clarification: bool = True
    prefers_concise: bool = False
    prefers_high_verification_for_code: bool = False
    max_parallelism: int = 4
    allowed_action_types: list[str] = field(default_factory=list)
    forbidden_action_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BehaviorPatternSummary:
    user_id: str
    tenant_id: str | None = None
    total_interactions: int = 0
    clarification_rate: float = 0.0
    correction_rate: float = 0.0
    tool_usage_distribution: dict[str, int] = field(default_factory=dict)
    agent_usage_rate: float = 0.0
    workflow_usage_rate: float = 0.0
    avg_session_length_minutes: float = 0.0
    preferred_time_of_day: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_tenant(self.tenant_id, "adaptive behavior summary")


@dataclass(slots=True)
class SystemCapabilitySnapshot:
    available_tools: list[str] = field(default_factory=list)
    available_agents: list[str] = field(default_factory=list)
    available_workflows: list[str] = field(default_factory=list)
    healthy_inference_targets: list[str] = field(default_factory=list)
    memory_available: bool = True
    local_only_mode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HistoricalEvidence:
    capability_profiles: JsonMap = field(default_factory=dict)
    agent_profiles: JsonMap = field(default_factory=dict)
    model_profiles: JsonMap = field(default_factory=dict)
    user_specific_evidence: JsonMap = field(default_factory=dict)
    global_evidence: JsonMap = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveContext:
    request_id: str
    correlation_id: str
    task_signature: Any
    user_state: UserStateSnapshot
    resolved_preferences: ResolvedPreferences
    behavior_patterns: BehaviorPatternSummary
    system_capabilities: SystemCapabilitySnapshot
    historical_evidence: HistoricalEvidence
    policy_version: str = "v1"
    feature_version: str = "v1"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreComponents:
    task_fit: float = 0.0
    user_preference_fit: float = 0.0
    historical_success: float = 0.0
    latency_penalty: float = 0.0
    risk_penalty: float = 0.0
    cost_penalty: float = 0.0
    interruption_penalty: float = 0.0
    confidence: float = 0.0
    custom_components: dict[str, float] = field(default_factory=dict)

    @property
    def utility(self) -> float:
        raw = (
            self.task_fit
            + self.user_preference_fit
            + self.historical_success
            + self.latency_penalty
            + self.risk_penalty
            + self.cost_penalty
            + self.interruption_penalty
        )
        return max(0.0, min(1.0, raw))


@dataclass(slots=True)
class AdaptiveRecommendation:
    recommendation_id: str
    action_type: AdaptiveActionType
    target_id: str | None = None
    utility_score: float = 0.0
    confidence: float = 0.0
    evidence: JsonMap = field(default_factory=dict)
    policy_constraints: JsonMap = field(default_factory=dict)
    explanation_codes: list[RecommendationReasonCode] = field(default_factory=list)
    score_components: ScoreComponents | None = None
    model_policy_version: str = "baseline"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveRecommendationSet:
    request_id: str
    correlation_id: str
    recommendations: list[AdaptiveRecommendation] = field(default_factory=list)
    shadow_mode: bool = False
    policy_version: str = "v1"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def top_recommendation(self) -> AdaptiveRecommendation | None:
        return self.recommendations[0] if self.recommendations else None


@dataclass(slots=True)
class SuggestionCandidate:
    suggestion_id: str
    suggestion_type: SuggestionType
    subject: str
    utility: float = 0.0
    confidence: float = 0.0
    interruption_cost: float = 0.0
    urgency: str = "normal"
    evidence: JsonMap = field(default_factory=dict)
    expires_at: datetime | None = None
    dedupe_key: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionOutcomeObservation:
    observation_id: str
    source_outcome_id: str
    task_signature_ref: dict[str, Any] = field(default_factory=dict)
    user_scope: JsonMap = field(default_factory=dict)
    action_type: str = ""
    target_id: str | None = None
    execution_status: str = ""
    latency_ms: float = 0.0
    fallback_used: bool = False
    tool_success: bool | None = None
    user_feedback: str | None = None
    correction: bool = False
    completion: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityPerformanceProfile:
    capability_id: str
    success_rate: float = 0.0
    failure_rate: float = 0.0
    median_latency_ms: float = 0.0
    retry_rate: float = 0.0
    correction_rate: float = 0.0
    sample_count: int = 0
    confidence_interval: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentPerformanceProfile:
    agent_id: str
    domain: str = ""
    task_type: str = ""
    success_rate: float = 0.0
    median_latency_ms: float = 0.0
    verification_success_rate: float = 0.0
    sample_count: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveHealth:
    candidate_generator: str = "unknown"
    historical_profiles: str = "unknown"
    suggestion_engine: str = "unknown"
    policy_evaluator: str = "unknown"
    queue_integration: str = "unknown"
    overall: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
