from __future__ import annotations

from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    LearningRewardVector,
    LearningScope,
    LearningSignalType,
    OutcomeAssessmentStatus,
    ProfileUpdateCandidate,
    ReflectionTrigger,
)


def test_learning_signal_type_values():
    assert LearningSignalType.POSITIVE_OUTCOME.value == "positive_outcome"
    assert LearningSignalType.VERIFICATION_CAUGHT_ERROR.value == "verification_caught_error"


def test_learning_scope_values():
    assert LearningScope.GLOBAL.value == "global"
    assert LearningScope.USER.value == "user"


def test_learning_reward_vector_aggregate():
    reward = LearningRewardVector(task_success=1.0, user_satisfaction=1.0, correctness=1.0, safety=1.0)
    assert reward.aggregate() > 0.0


def test_outcome_assessment_status_values():
    assert OutcomeAssessmentStatus.SUCCESS.value == "success"
    assert OutcomeAssessmentStatus.ABORTED.value == "aborted"


def test_experience_observation_tenant():
    exp = ExperienceObservation(observation_id="e1", what_was_tried="t", why_chosen="c", tenant_id="tenant-a")
    assert exp.tenant_id == "tenant-a"


def test_profile_update_candidate_scope():
    cand = ProfileUpdateCandidate(candidate_id="c1", profile_type="capability", target_id="cap1", scope=LearningScope.TENANT)
    assert cand.scope == LearningScope.TENANT


def test_reflection_trigger_creation():
    trigger = ReflectionTrigger(trigger_id="t1", trigger_type="repeated_failure", experience_ids=["e1", "e2"])
    assert trigger.trigger_type == "repeated_failure"
