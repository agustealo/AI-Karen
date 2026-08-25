from __future__ import annotations

import pytest

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
from ai_karen_engine.config.cognitive.validation import (
    CognitiveConfigValidationError,
    validate_behavior,
    validate_belief,
    validate_cognitive_policy,
    validate_context,
    validate_learning,
    validate_memory,
    validate_meta_cognition,
    validate_salience,
)


def test_valid_cognitive_policy_passes():
    policy = CognitivePolicyConfig()
    validate_cognitive_policy(policy)


def test_meta_cognition_invalid_weak_memory_threshold():
    config = MetaCognitionPolicyConfig(weak_memory_threshold=-0.1)
    with pytest.raises(CognitiveConfigValidationError):
        validate_meta_cognition(config)


def test_meta_cognition_invalid_low_reasoning_threshold():
    config = MetaCognitionPolicyConfig(low_reasoning_threshold=1.5)
    with pytest.raises(CognitiveConfigValidationError):
        validate_meta_cognition(config)


def test_meta_cognition_invalid_loop_repeat_threshold():
    config = MetaCognitionPolicyConfig(loop_repeat_threshold=1)
    with pytest.raises(CognitiveConfigValidationError):
        validate_meta_cognition(config)


def test_meta_cognition_invalid_max_reconsideration_steps():
    config = MetaCognitionPolicyConfig(max_reconsideration_steps=0)
    with pytest.raises(CognitiveConfigValidationError):
        validate_meta_cognition(config)


def test_meta_cognition_invalid_confidence_threshold_order():
    config = MetaCognitionPolicyConfig(confidence_threshold_low=0.8, confidence_threshold_high=0.3)
    with pytest.raises(CognitiveConfigValidationError):
        validate_meta_cognition(config)


def test_belief_invalid_staleness_threshold():
    config = BeliefPolicyConfig(staleness_threshold_hours=-1)
    with pytest.raises(CognitiveConfigValidationError):
        validate_belief(config)


def test_belief_invalid_contradiction_ratio():
    config = BeliefPolicyConfig(max_contradiction_ratio_for_rejection=1.5)
    with pytest.raises(CognitiveConfigValidationError):
        validate_belief(config)


def test_salience_invalid_decay_rate():
    config = SaliencePolicyConfig(default_decay_rate=-0.5)
    with pytest.raises(CognitiveConfigValidationError):
        validate_salience(config)


def test_salience_invalid_min_max():
    config = SaliencePolicyConfig(min_salience_threshold=0.8, max_salience_value=0.5)
    with pytest.raises(CognitiveConfigValidationError):
        validate_salience(config)


def test_context_invalid_max_items():
    config = ContextPolicyConfig(max_items=0)
    with pytest.raises(CognitiveConfigValidationError):
        validate_context(config)


def test_context_reserved_exceeds_max():
    config = ContextPolicyConfig(max_items=5, reserved_for_critical=10)
    with pytest.raises(CognitiveConfigValidationError):
        validate_context(config)


def test_behavior_invalid_risk_weight():
    config = BehaviorPolicyConfig(risk_penalty_weight=-1.0)
    with pytest.raises(CognitiveConfigValidationError):
        validate_behavior(config)


def test_behavior_invalid_utility_floor():
    config = BehaviorPolicyConfig(utility_floor=0.8, utility_ceiling=0.5)
    with pytest.raises(CognitiveConfigValidationError):
        validate_behavior(config)


def test_learning_invalid_min_samples():
    config = LearningPolicyConfig(min_samples=0)
    with pytest.raises(CognitiveConfigValidationError):
        validate_learning(config)


def test_learning_invalid_confidence_order():
    config = LearningPolicyConfig(min_confidence_explicit=0.5, min_confidence_inferred=0.9)
    with pytest.raises(CognitiveConfigValidationError):
        validate_learning(config)


def test_learning_invalid_pattern_confidence_order():
    config = LearningPolicyConfig(
        reflection_pattern_confidence_base=0.9,
        reflection_pattern_max_confidence=0.7,
    )
    with pytest.raises(CognitiveConfigValidationError):
        validate_learning(config)


def test_memory_invalid_decay_lambda():
    config = MemoryPolicyConfig(default_decay_lambda=-0.1)
    with pytest.raises(CognitiveConfigValidationError):
        validate_memory(config)


def test_memory_importance_out_of_range():
    config = MemoryPolicyConfig(default_importance_score=15.0)
    with pytest.raises(CognitiveConfigValidationError):
        validate_memory(config)


def test_full_policy_validates_children():
    policy = CognitivePolicyConfig(
        meta=MetaCognitionPolicyConfig(loop_repeat_threshold=2),
        belief=BeliefPolicyConfig(staleness_threshold_hours=24),
        salience=SaliencePolicyConfig(default_decay_rate=0.05),
        context=ContextPolicyConfig(max_items=10, reserved_for_critical=2),
        behavior=BehaviorPolicyConfig(risk_penalty_weight=2.0),
        learning=LearningPolicyConfig(min_samples=50),
        memory=MemoryPolicyConfig(default_decay_lambda=0.1),
    )
    validate_cognitive_policy(policy)
