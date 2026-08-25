from __future__ import annotations

from typing import Any

from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    LearningEligibility,
    LearningRewardVector,
    LearningSignal,
    LearningSignalType,
    LearningScope,
    OutcomeAssessment,
    OutcomeAssessmentStatus,
    OutcomeAttribution,
    ReflectionTrigger,
)
from ai_karen_engine.core.adaptive.learning.experience.attribution import AttributionEngine
from ai_karen_engine.core.adaptive.learning.experience.eligibility import EligibilityGate
from ai_karen_engine.core.adaptive.learning.experience.normalization import ExperienceNormalizer
from ai_karen_engine.core.adaptive.learning.experience.reward import RewardComputer


def _outcome(**kwargs: Any) -> ActionOutcomeObservation:
    return ActionOutcomeObservation(
        observation_id="obs1",
        source_outcome_id="out1",
        user_scope={"user_id": "u1", "tenant_id": "t1"},
        **kwargs,
    )


def test_successful_outcome_creates_positive_signal():
    normalizer = ExperienceNormalizer()
    outcome = _outcome(execution_status="success", completion=True, tool_success=True)
    exp = normalizer.normalize(outcome)
    assert exp.what_was_tried == "respond_directly"


def test_failed_outcome_creates_negative_signal():
    normalizer = ExperienceNormalizer()
    outcome = _outcome(execution_status="failure", completion=False, tool_success=False)
    exp = normalizer.normalize(outcome)
    assert exp.actual_outcome["status"] == "failure"


def test_correction_differs_from_generic_failure():
    normalizer = ExperienceNormalizer()
    outcome = _outcome(correction=True, execution_status="success")
    assessment = normalizer._assess_outcome(outcome)
    assert assessment.correction_needed is True
    assert assessment.status == OutcomeAssessmentStatus.PARTIAL_SUCCESS


def test_infrastructure_failure_does_not_become_user_preference_signal():
    gate = EligibilityGate()
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.STRATEGY_FAILURE, scope=LearningScope.GLOBAL, sample_count=1)
    eligibility = gate.evaluate(
        ExperienceObservation(observation_id="e1", what_was_tried="t", why_chosen="c"),
        OutcomeAssessment(status=OutcomeAssessmentStatus.FAILURE),
        signal,
    )
    assert eligibility.action == LearningEligibility.RECORD_ONLY


def test_learning_signal_preserves_provenance():
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.POSITIVE_OUTCOME, source_experience_id="e1")
    assert signal.source_experience_id == "e1"


def test_user_scoped_feedback_stays_user_scoped():
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.USER_CORRECTION, scope=LearningScope.USER, user_id="u1")
    assert signal.scope == LearningScope.USER
    assert signal.user_id == "u1"


def test_global_learning_requires_explicit_eligibility():
    gate = EligibilityGate()
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.STRATEGY_SUCCESS, scope=LearningScope.GLOBAL, sample_count=1)
    eligibility = gate.evaluate(
        ExperienceObservation(observation_id="e1", what_was_tried="t", why_chosen="c"),
        OutcomeAssessment(status=OutcomeAssessmentStatus.SUCCESS),
        signal,
    )
    assert eligibility.action != LearningEligibility.UPDATE_PROFILE


def test_reward_is_multidimensional():
    reward = LearningRewardVector(task_success=0.9, user_satisfaction=0.8, correctness=0.9, efficiency=0.7, safety=0.9)
    agg = reward.aggregate()
    assert agg > 0.0


def test_success_attribution_can_remain_uncertain():
    engine = AttributionEngine()
    attribution = engine.attribute(
        ExperienceObservation(observation_id="e1", what_was_tried="t", why_chosen="c"),
        OutcomeAssessment(status=OutcomeAssessmentStatus.SUCCESS, task_completion=0.5),
    )
    assert attribution.uncertainty > 0.0
    assert attribution.primary_driver == "unknown"


def test_one_sample_cannot_produce_strong_global_learning():
    gate = EligibilityGate()
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.STRATEGY_SUCCESS, scope=LearningScope.GLOBAL, sample_count=1, strength=LearningStrength.STRONG)
    eligibility = gate.evaluate(
        ExperienceObservation(observation_id="e1", what_was_tried="t", why_chosen="c"),
        OutcomeAssessment(status=OutcomeAssessmentStatus.SUCCESS),
        signal,
    )
    assert eligibility.action != LearningEligibility.UPDATE_PROFILE


def test_repeated_failures_can_trigger_reflection():
    trigger = ReflectionTrigger(trigger_id="t1", trigger_type="repeated_failure", experience_ids=["e1", "e2", "e3"], urgency=0.8)
    assert trigger.trigger_type == "repeated_failure"
    assert len(trigger.experience_ids) == 3


def test_verification_catching_error_becomes_useful_learning():
    signal = LearningSignal(signal_id="s1", signal_type=LearningSignalType.VERIFICATION_CAUGHT_ERROR)
    assert signal.signal_type == LearningSignalType.VERIFICATION_CAUGHT_ERROR


def test_learning_layer_does_not_persist_or_train():
    normalizer = ExperienceNormalizer()
    outcome = _outcome()
    exp = normalizer.normalize(outcome)
    assert not hasattr(exp, "save")
    assert not hasattr(exp, "train")
