from __future__ import annotations

from ai_karen_engine.config.cognitive.defaults import (
    DEFAULT_COGNITIVE_POLICY,
    behavior_defaults,
    belief_defaults,
    cognitive_policy_defaults,
    context_defaults,
    learning_defaults,
    memory_defaults,
    meta_cognition_defaults,
    salience_defaults,
)


def test_cognitive_policy_defaults_are_created():
    policy = cognitive_policy_defaults()
    assert policy.schema_version == "1"
    assert policy.policy_version == "cognitive-v1"
    assert policy.scoring_version == "weighted-v1"


def test_default_cognitive_policy_is_singleton():
    assert DEFAULT_COGNITIVE_POLICY is not None
    assert DEFAULT_COGNITIVE_POLICY.schema_version == "1"


def test_meta_cognition_defaults():
    meta = meta_cognition_defaults()
    assert meta.weak_memory_threshold == 0.4
    assert meta.low_reasoning_threshold == 0.3
    assert meta.verification_threshold == 0.3
    assert meta.deep_reasoning_threshold == 0.4
    assert meta.loop_repeat_threshold == 3
    assert meta.max_reconsideration_steps == 1
    assert meta.confidence_threshold_low == 0.4
    assert meta.confidence_threshold_high == 0.7
    assert meta.performance_window == 10
    assert meta.enable_adaptive_thresholds is True


def test_belief_defaults():
    belief = belief_defaults()
    assert belief.staleness_threshold_hours == 168.0
    assert belief.min_confidence_for_verification == 0.8
    assert belief.min_evidence_for_established == 1
    assert belief.min_confidence_for_established == 0.7
    assert belief.max_contradiction_ratio_for_rejection == 0.3
    assert belief.evidence_strength_weights["strong"] == 0.85
    assert belief.source_credibility["user_statement"] == 0.85


def test_salience_defaults():
    salience = salience_defaults()
    assert salience.default_decay_rate == 0.1
    assert salience.retrigger_boost == 0.1
    assert salience.habituation_decay_factor == 0.05
    assert salience.dimension_decay_rates["novelty"] == 0.1
    assert salience.dimension_decay_rates["urgency"] == 0.2
    assert salience.aggregation_mode == "max"


def test_context_defaults():
    context = context_defaults()
    assert context.max_items == 20
    assert context.max_tokens == 4096
    assert context.reserved_for_critical == 2
    assert context.priority_weights["critical"] == 1000
    assert context.freshness_modifiers["real_time"] == 50
    assert context.trust_modifiers["explicit"] == 0


def test_behavior_defaults():
    behavior = behavior_defaults()
    assert behavior.risk_penalty_weight == 1.0
    assert behavior.interruption_penalty_weight == 1.0
    assert behavior.verification_value_weight == 1.0
    assert behavior.goal_alignment_weights["reason"] == 0.9
    assert behavior.abstain_confidence_threshold == 0.3
    assert behavior.verification_verify == 0.9
    assert behavior.interruption_ask == 0.3


def test_learning_defaults():
    learning = learning_defaults()
    assert learning.min_samples == 100
    assert learning.min_confidence == 0.95
    assert learning.min_explicit_evidence == 1
    assert learning.min_inferred_evidence == 3
    assert learning.min_source_diversity == 2
    assert learning.min_confidence_explicit == 0.8
    assert learning.min_confidence_inferred == 0.7
    assert learning.max_contradiction_ratio == 0.3
    assert learning.min_salience == 0.4
    assert learning.max_events_per_session == 100
    assert learning.min_confidence_for_candidate == 0.3


def test_memory_defaults():
    memory = memory_defaults()
    assert memory.default_decay_lambda == 0.08
    assert memory.default_importance_score == 5.0
    assert memory.default_confidence == 1.0
    assert memory.decay_lambdas["episodic"] == 0.12
    assert memory.decay_lambdas["semantic"] == 0.04
    assert memory.decay_lambdas["procedural"] == 0.02


def test_all_defaults_reproduce_current_behavior():
    policy = cognitive_policy_defaults()
    assert policy.meta.weak_memory_threshold == 0.4
    assert policy.behavior.interruption_ask == 0.3
    assert policy.context.max_items == 20
    assert policy.salience.default_decay_rate == 0.1
    assert policy.learning.min_samples == 100
    assert policy.memory.default_decay_lambda == 0.08
