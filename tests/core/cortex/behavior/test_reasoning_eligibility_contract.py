from __future__ import annotations

import pytest

from ai_karen_engine.core.cortex.reasoning_eligibility import (
    EligibilityDisposition,
    ReasoningEligibilityDecision,
    ReasoningModeEligibility,
)


def test_reasoning_mode_eligibility_normalizes_aliases() -> None:
    assessment = ReasoningModeEligibility(
        mode="verify",
        disposition=EligibilityDisposition.ELIGIBLE,
        expected_utility=0.7,
        confidence=0.8,
        estimated_model_calls=1,
    )

    assert assessment.mode == "verification"


def test_reasoning_eligibility_selected_modes_require_eligible_assessment() -> None:
    with pytest.raises(ValueError, match="not eligible"):
        ReasoningEligibilityDecision(
            assessments=(
                ReasoningModeEligibility(
                    mode="soft_exploration",
                    disposition=EligibilityDisposition.INELIGIBLE,
                    expected_utility=0.2,
                    confidence=0.9,
                    rejection_reasons=("insufficient_expected_value",),
                ),
            ),
            selected_modes=("soft_exploration",),
            decision_confidence=0.9,
        )


def test_reasoning_eligibility_selected_modes_require_assessment() -> None:
    with pytest.raises(ValueError, match="missing eligibility assessment"):
        ReasoningEligibilityDecision(
            assessments=(),
            selected_modes=("causal",),
            decision_confidence=0.8,
        )


def test_reasoning_eligibility_aggregates_selected_costs_only() -> None:
    decision = ReasoningEligibilityDecision(
        assessments=(
            ReasoningModeEligibility(
                mode="causal",
                disposition=EligibilityDisposition.ELIGIBLE,
                expected_utility=0.6,
                confidence=0.8,
                estimated_model_calls=2,
                estimated_latency_ms=100,
            ),
            ReasoningModeEligibility(
                mode="soft_exploration",
                disposition=EligibilityDisposition.ELIGIBLE,
                expected_utility=0.9,
                confidence=0.75,
                estimated_model_calls=30,
                estimated_latency_ms=2500,
            ),
        ),
        selected_modes=("soft",),
        decision_confidence=0.75,
        reason_codes=("high_expected_value",),
    )

    assert decision.selected_modes == ("soft_exploration",)
    assert decision.eligible_modes == ("causal", "soft_exploration")
    assert decision.estimated_model_calls == 30
    assert decision.estimated_latency_ms == 2500


def test_eligible_assessment_cannot_carry_rejection_reasons() -> None:
    with pytest.raises(ValueError, match="cannot carry rejection reasons"):
        ReasoningModeEligibility(
            mode="causal",
            disposition=EligibilityDisposition.ELIGIBLE,
            expected_utility=0.5,
            confidence=0.5,
            rejection_reasons=("contradiction",),
        )


def test_reasoning_eligibility_rejects_invalid_score_domain() -> None:
    with pytest.raises(ValueError, match="expected_utility"):
        ReasoningModeEligibility(
            mode="causal",
            disposition=EligibilityDisposition.ELIGIBLE,
            expected_utility=1.1,
            confidence=0.5,
        )
