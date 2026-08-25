from __future__ import annotations

from ai_karen_engine.config.cognitive.models import (
    BehaviorPolicyConfig,
    BeliefPolicyConfig,
    CognitivePolicyConfig,
    ContextPolicyConfig,
    LearningPolicyConfig,
    MemoryPolicyConfig,
    MetaCognitionPolicyConfig,
    SaliencePolicyConfig,
)


class CognitiveConfigValidationError(Exception):
    """Raised when cognitive configuration values are invalid."""


def _validate_threshold(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise CognitiveConfigValidationError(
            f"{name} must be between 0.0 and 1.0, got {value}"
        )


def _validate_weight(value: float, name: str) -> None:
    if value < 0.0:
        raise CognitiveConfigValidationError(
            f"{name} must be >= 0.0, got {value}"
        )


def _validate_positive(value: int, name: str) -> None:
    if value < 1:
        raise CognitiveConfigValidationError(
            f"{name} must be >= 1, got {value}"
        )


def _validate_non_negative(value: int, name: str) -> None:
    if value < 0:
        raise CognitiveConfigValidationError(
            f"{name} must be >= 0, got {value}"
        )


def validate_meta_cognition(config: MetaCognitionPolicyConfig) -> None:
    _validate_threshold(config.weak_memory_threshold, "weak_memory_threshold")
    _validate_threshold(config.low_reasoning_threshold, "low_reasoning_threshold")
    _validate_threshold(config.verification_threshold, "verification_threshold")
    _validate_threshold(config.deep_reasoning_threshold, "deep_reasoning_threshold")
    _validate_threshold(config.confidence_threshold_low, "confidence_threshold_low")
    _validate_threshold(config.confidence_threshold_high, "confidence_threshold_high")
    _validate_threshold(config.min_confidence_for_self_correction, "min_confidence_for_self_correction")
    _validate_threshold(config.quality_below_threshold, "quality_below_threshold")
    _validate_threshold(config.stuck_confidence_threshold, "stuck_confidence_threshold")
    _validate_threshold(config.stuck_certainty_threshold, "stuck_certainty_threshold")
    _validate_threshold(config.uncertain_certainty_threshold, "uncertain_certainty_threshold")
    _validate_threshold(config.exploring_confidence_threshold, "exploring_confidence_threshold")
    _validate_threshold(config.consolidating_confidence_min, "consolidating_confidence_min")
    _validate_threshold(config.consolidating_confidence_max, "consolidating_confidence_max")
    _validate_threshold(config.success_rate_low, "success_rate_low")
    _validate_threshold(config.success_rate_high, "success_rate_high")
    _validate_positive(config.loop_repeat_threshold, "loop_repeat_threshold")
    _validate_positive(config.max_reconsideration_steps, "max_reconsideration_steps")
    _validate_positive(config.performance_window, "performance_window")
    _validate_positive(config.min_tasks_for_adaptation, "min_tasks_for_adaptation")
    _validate_non_negative(config.confused_knowledge_gap_threshold, "confused_knowledge_gap_threshold")
    if config.loop_repeat_threshold < 2:
        raise CognitiveConfigValidationError(
            f"loop_repeat_threshold must be >= 2, got {config.loop_repeat_threshold}"
        )
    if config.confidence_threshold_low >= config.confidence_threshold_high:
        raise CognitiveConfigValidationError(
            "confidence_threshold_low must be less than confidence_threshold_high"
        )


def validate_belief(config: BeliefPolicyConfig) -> None:
    _validate_threshold(config.min_confidence_for_verification, "min_confidence_for_verification")
    _validate_positive(config.staleness_threshold_hours, "staleness_threshold_hours")
    _validate_positive(config.min_evidence_for_established, "min_evidence_for_established")
    _validate_threshold(config.min_confidence_for_established, "min_confidence_for_established")
    _validate_threshold(config.max_contradiction_ratio_for_rejection, "max_contradiction_ratio_for_rejection")
    _validate_weight(config.revision_weaken_amount, "revision_weaken_amount")
    for name, weight in config.evidence_strength_weights.items():
        _validate_weight(weight, f"evidence_strength_weights.{name}")
    for name, weight in config.source_credibility.items():
        _validate_weight(weight, f"source_credibility.{name}")


def validate_salience(config: SaliencePolicyConfig) -> None:
    _validate_threshold(config.default_decay_rate, "default_decay_rate")
    _validate_weight(config.retrigger_boost, "retrigger_boost")
    _validate_weight(config.habituation_decay_factor, "habituation_decay_factor")
    _validate_threshold(config.min_salience_threshold, "min_salience_threshold")
    _validate_threshold(config.max_salience_value, "max_salience_value")
    for name, rate in config.dimension_decay_rates.items():
        _validate_threshold(rate, f"dimension_decay_rates.{name}")
    if config.min_salience_threshold > config.max_salience_value:
        raise CognitiveConfigValidationError(
            "min_salience_threshold must be <= max_salience_value"
        )


def validate_context(config: ContextPolicyConfig) -> None:
    _validate_positive(config.max_items, "max_items")
    _validate_positive(config.max_tokens, "max_tokens")
    _validate_non_negative(config.reserved_for_critical, "reserved_for_critical")
    _validate_positive(config.requirement_max_items_default, "requirement_max_items_default")
    if config.reserved_for_critical > config.max_items:
        raise CognitiveConfigValidationError(
            f"reserved_for_critical ({config.reserved_for_critical}) must be <= max_items ({config.max_items})"
        )


def validate_behavior(config: BehaviorPolicyConfig) -> None:
    _validate_weight(config.risk_penalty_weight, "risk_penalty_weight")
    _validate_weight(config.interruption_penalty_weight, "interruption_penalty_weight")
    _validate_weight(config.verification_value_weight, "verification_value_weight")
    _validate_threshold(config.abstain_confidence_threshold, "abstain_confidence_threshold")
    _validate_threshold(config.utility_floor, "utility_floor")
    _validate_threshold(config.utility_ceiling, "utility_ceiling")
    for name, weight in config.goal_alignment_weights.items():
        _validate_weight(weight, f"goal_alignment_weights.{name}")
    if config.utility_floor > config.utility_ceiling:
        raise CognitiveConfigValidationError(
            "utility_floor must be <= utility_ceiling"
        )


def validate_learning(config: LearningPolicyConfig) -> None:
    _validate_positive(config.min_samples, "min_samples")
    _validate_threshold(config.min_confidence, "min_confidence")
    _validate_weight(config.max_importance_weight, "max_importance_weight")
    _validate_weight(config.min_gain, "min_gain")
    _validate_threshold(config.max_segment_regression, "max_segment_regression")
    _validate_threshold(config.max_estimator_disagreement, "max_estimator_disagreement")
    _validate_positive(config.min_explicit_evidence, "min_explicit_evidence")
    _validate_positive(config.min_inferred_evidence, "min_inferred_evidence")
    _validate_positive(config.min_source_diversity, "min_source_diversity")
    _validate_threshold(config.min_confidence_explicit, "min_confidence_explicit")
    _validate_threshold(config.min_confidence_inferred, "min_confidence_inferred")
    _validate_threshold(config.max_contradiction_ratio, "max_contradiction_ratio")
    _validate_threshold(config.min_salience, "min_salience")
    _validate_positive(config.time_distribution_min, "time_distribution_min")
    _validate_threshold(config.risk_threshold, "risk_threshold")
    _validate_positive(config.max_events_per_session, "max_events_per_session")
    _validate_threshold(config.min_confidence_for_candidate, "min_confidence_for_candidate")
    _validate_positive(config.deduplication_window_hours, "deduplication_window_hours")
    _validate_threshold(config.min_confidence_for_rejection, "min_confidence_for_rejection")
    _validate_threshold(config.min_confidence_for_reinforce, "min_confidence_for_reinforce")
    _validate_threshold(config.reflection_success_confidence, "reflection_success_confidence")
    _validate_threshold(config.reflection_success_salience, "reflection_success_salience")
    _validate_threshold(config.reflection_pattern_confidence_base, "reflection_pattern_confidence_base")
    _validate_threshold(config.reflection_pattern_confidence_per_item, "reflection_pattern_confidence_per_item")
    _validate_threshold(config.reflection_pattern_max_confidence, "reflection_pattern_max_confidence")
    _validate_threshold(config.reflection_preference_confidence, "reflection_preference_confidence")
    _validate_threshold(config.reflection_preference_salience, "reflection_preference_salience")
    _validate_threshold(config.reflection_goal_confidence, "reflection_goal_confidence")
    _validate_threshold(config.reflection_failure_confidence, "reflection_failure_confidence")
    _validate_threshold(config.reflection_failure_salience, "reflection_failure_salience")
    _validate_positive(config.min_successes_for_pattern, "min_successes_for_pattern")
    if config.min_confidence_explicit <= config.min_confidence_inferred:
        raise CognitiveConfigValidationError(
            "min_confidence_explicit must be greater than min_confidence_inferred"
        )
    if config.reflection_pattern_max_confidence < config.reflection_pattern_confidence_base:
        raise CognitiveConfigValidationError(
            "reflection_pattern_max_confidence must be >= reflection_pattern_confidence_base"
        )


def validate_memory(config: MemoryPolicyConfig) -> None:
    _validate_threshold(config.default_decay_lambda, "default_decay_lambda")
    _validate_weight(config.default_importance_score, "default_importance_score")
    _validate_threshold(config.default_confidence, "default_confidence")
    for name, lam in config.decay_lambdas.items():
        _validate_threshold(lam, f"decay_lambdas.{name}")
    if not (config.importance_scale_min <= config.default_importance_score <= config.importance_scale_max):
        raise CognitiveConfigValidationError(
            f"default_importance_score must be between {config.importance_scale_min} and {config.importance_scale_max}"
        )
    if not (config.confidence_min <= config.default_confidence <= config.confidence_max):
        raise CognitiveConfigValidationError(
            f"default_confidence must be between {config.confidence_min} and {config.confidence_max}"
        )


def validate_cognitive_policy(config: CognitivePolicyConfig) -> None:
    validate_meta_cognition(config.meta)
    validate_belief(config.belief)
    validate_salience(config.salience)
    validate_context(config.context)
    validate_behavior(config.behavior)
    validate_learning(config.learning)
    validate_memory(config.memory)
