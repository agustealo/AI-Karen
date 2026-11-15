"""KCOG-00B1: outcome heuristics cannot manufacture causal attribution."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.learning.experience.attribution import (
    AttributionEngine,
)
from ai_karen_engine.core.adaptive.learning.experience.contracts import (
    ExperienceObservation,
    OutcomeAssessment,
    OutcomeAssessmentStatus,
)


def test_success_and_acceptance_do_not_establish_causal_contributions() -> None:
    attribution = AttributionEngine().attribute(
        ExperienceObservation(
            observation_id="sample",
            what_was_tried="solve_task",
            why_chosen="policy",
            belief_refs=["existing-memory"],
        ),
        OutcomeAssessment(
            status=OutcomeAssessmentStatus.SUCCESS,
            task_completion=1.0,
            user_acceptance=1.0,
        ),
    )

    assert attribution.primary_driver == "unknown"
    assert attribution.metadata["status"] == "unidentified"
    assert attribution.memory_contribution is None
    assert attribution.capability_contribution is None
    assert attribution.reasoning_strategy_contribution is None
    assert attribution.uncertainty is None


def test_correction_does_not_infer_memory_causation() -> None:
    attribution = AttributionEngine().attribute(
        ExperienceObservation(
            observation_id="sample",
            what_was_tried="solve_task",
            why_chosen="policy",
        ),
        OutcomeAssessment(
            status=OutcomeAssessmentStatus.PARTIAL_SUCCESS,
            correction_needed=True,
        ),
    )

    assert attribution.primary_driver == "unknown"
    assert attribution.user_clarification_contribution is None
    assert attribution.verification_contribution is None
    assert attribution.metadata["reason"] == "no_verified_causal_attribution_design"
