from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class CognitivePolicyConfig:
    schema_version: str = "1"
    policy_version: str = "cognitive-v1"
    scoring_version: str = "weighted-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: MetaCognitionPolicyConfig = field(default_factory=lambda: MetaCognitionPolicyConfig())
    belief: BeliefPolicyConfig = field(default_factory=lambda: BeliefPolicyConfig())
    salience: SaliencePolicyConfig = field(default_factory=lambda: SaliencePolicyConfig())
    context: ContextPolicyConfig = field(default_factory=lambda: ContextPolicyConfig())
    behavior: BehaviorPolicyConfig = field(default_factory=lambda: BehaviorPolicyConfig())
    learning: LearningPolicyConfig = field(default_factory=lambda: LearningPolicyConfig())
    memory: MemoryPolicyConfig = field(default_factory=lambda: MemoryPolicyConfig())


@dataclass(slots=True)
class MetaCognitionPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "meta-cognition-v1"
    scoring_version: str = "threshold-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    weak_memory_threshold: float = 0.4
    low_reasoning_threshold: float = 0.3
    verification_threshold: float = 0.3
    deep_reasoning_threshold: float = 0.4
    loop_repeat_threshold: int = 3
    max_reconsideration_steps: int = 1
    confidence_threshold_low: float = 0.4
    confidence_threshold_high: float = 0.7
    performance_window: int = 10
    enable_adaptive_thresholds: bool = True
    min_confidence_for_self_correction: float = 0.6
    quality_below_threshold: float = 0.6
    stuck_confidence_threshold: float = 0.3
    stuck_certainty_threshold: float = 0.3
    confused_knowledge_gap_threshold: int = 3
    uncertain_certainty_threshold: float = 0.4
    exploring_confidence_threshold: float = 0.6
    consolidating_confidence_min: float = 0.6
    consolidating_confidence_max: float = 0.8
    success_rate_low: float = 0.5
    success_rate_high: float = 0.8
    performance_alpha: float = 0.2
    min_tasks_for_adaptation: int = 5


@dataclass(slots=True)
class BeliefPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "belief-v1"
    scoring_version: str = "evidence-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    staleness_threshold_hours: float = 168.0
    min_confidence_for_verification: float = 0.8
    min_confidence_for_revision_weaken: float = 0.0
    revision_weaken_amount: float = 0.2
    evidence_strength_weights: dict[str, float] = field(default_factory=lambda: {
        "weak": 0.3,
        "moderate": 0.6,
        "strong": 0.85,
        "definitive": 1.0,
    })
    source_credibility: dict[str, float] = field(default_factory=lambda: {
        "user_statement": 0.85,
        "observation": 0.6,
        "tool_result": 0.7,
        "memory": 0.5,
        "document": 0.6,
        "external_source": 0.4,
        "system_inference": 0.3,
        "outcome": 0.75,
    })
    min_evidence_for_established: int = 1
    min_confidence_for_established: float = 0.7
    max_contradiction_ratio_for_rejection: float = 0.3


@dataclass(slots=True)
class SaliencePolicyConfig:
    schema_version: str = "1"
    policy_version: str = "salience-v1"
    scoring_version: str = "aggregation-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    default_decay_rate: float = 0.1
    default_persistence_class: str = "standard"
    retrigger_boost: float = 0.1
    habituation_decay_factor: float = 0.05
    dimension_decay_rates: dict[str, float] = field(default_factory=lambda: {
        "novelty": 0.1,
        "urgency": 0.2,
        "goal_relevance": 0.05,
        "relationship_importance": 0.03,
        "risk": 0.15,
        "surprise": 0.2,
        "reward_significance": 0.1,
        "failure_significance": 0.05,
        "success_significance": 0.1,
        "repetition": 0.1,
        "contradiction": 0.05,
        "interruption_cost": 0.2,
    })
    aggregation_mode: str = "max"
    min_salience_threshold: float = 0.0
    max_salience_value: float = 1.0


@dataclass(slots=True)
class ContextPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "context-v1"
    scoring_version: str = "weighted-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    max_items: int = 20
    max_tokens: int = 4096
    reserved_for_critical: int = 2
    priority_floor: str = "minimal"
    min_trust_level: str = "low_confidence"
    priority_weights: dict[str, int] = field(default_factory=lambda: {
        "critical": 1000,
        "high": 750,
        "medium": 500,
        "low": 250,
        "minimal": 0,
    })
    reason_modifiers: dict[str, int] = field(default_factory=lambda: {
        "active_goal": 300,
        "explicit_user_fact": 250,
        "high_salience_memory": 200,
        "policy_requirement": 200,
        "unresolved_intention": 150,
        "recent_relevant": 100,
        "explicit_override": 100,
        "conversational_trivia": -400,
        "stale_fact": -500,
        "recent_irrelevant": -300,
        "inferred_assumption": -100,
        "token_pressure": -200,
        "contradicted": -1000,
    })
    freshness_modifiers: dict[str, int] = field(default_factory=lambda: {
        "real_time": 50,
        "recent": 30,
        "short_lived": 10,
        "long_lived": 20,
        "static": 5,
        "stale": -500,
    })
    trust_modifiers: dict[str, int] = field(default_factory=lambda: {
        "explicit": 0,
        "inferred": -20,
        "assumed": -50,
        "low_confidence": -80,
        "contradicted": -1000,
    })
    conflict_penalty: int = -1000
    requirement_max_items_default: int = 3


@dataclass(slots=True)
class BehaviorPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "behavior-v1"
    scoring_version: str = "weighted-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    risk_penalty_weight: float = 1.0
    interruption_penalty_weight: float = 1.0
    verification_value_weight: float = 1.0
    goal_alignment_weights: dict[str, float] = field(default_factory=lambda: {
        "use_workflow": 0.9,
        "reason": 0.9,
        "recall": 0.9,
        "default": 0.4,
    })
    belief_support_default: float = 0.5
    salience_fit_multiplier: float = 0.8
    user_preference_action: float = 0.7
    user_preference_clarification: float = 0.5
    historical_success_default: float = 0.5
    historical_success_min: float = 0.5
    capability_fit_no_requirements: float = 0.8
    capability_fit_use_capability: float = 0.9
    capability_fit_default: float = 0.7
    policy_fit_blocked: float = 0.0
    policy_fit_allowed: float = 1.0
    interruption_ask: float = 0.3
    interruption_default: float = 0.1
    verification_verify: float = 0.9
    verification_default: float = 0.1
    abstain_confidence_threshold: float = 0.3
    utility_floor: float = 0.0
    utility_ceiling: float = 1.0


@dataclass(slots=True)
class LearningPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "learning-v1"
    scoring_version: str = "promotion-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    min_samples: int = 100
    min_confidence: float = 0.95
    require_dr: bool = True
    require_snips: bool = True
    max_importance_weight: float = 100.0
    min_gain: float = 0.0
    max_segment_regression: float = 0.05
    max_estimator_disagreement: float = 0.1
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
    max_events_per_session: int = 100
    detect_failures: bool = True
    detect_successes: bool = True
    detect_patterns: bool = True
    detect_preferences: bool = True
    detect_goals: bool = True
    min_confidence_for_candidate: float = 0.3
    deduplication_window_hours: float = 24.0
    min_confidence_for_rejection: float = 0.2
    min_confidence_for_reinforce: float = 0.9
    reflection_success_confidence: float = 0.4
    reflection_success_salience: float = 0.5
    reflection_pattern_confidence_base: float = 0.3
    reflection_pattern_confidence_per_item: float = 0.15
    reflection_pattern_max_confidence: float = 0.9
    reflection_preference_confidence: float = 0.85
    reflection_preference_salience: float = 0.9
    reflection_goal_confidence: float = 0.7
    reflection_failure_confidence: float = 0.7
    reflection_failure_salience: float = 0.8
    min_successes_for_pattern: int = 2


@dataclass(slots=True)
class MemoryPolicyConfig:
    schema_version: str = "1"
    policy_version: str = "memory-v1"
    scoring_version: str = "decay-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    default_decay_lambda: float = 0.08
    default_importance_score: float = 5.0
    default_confidence: float = 1.0
    decay_lambdas: dict[str, float] = field(default_factory=lambda: {
        "episodic": 0.12,
        "semantic": 0.04,
        "procedural": 0.02,
    })
    importance_scale_min: float = 1.0
    importance_scale_max: float = 10.0
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    decay_lambda_min: float = 0.0
    decay_lambda_max: float = 1.0
