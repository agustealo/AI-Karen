from __future__ import annotations

import pytest

from ai_karen_engine.core.adaptive.salience.contracts import (
    ExpectedState,
    GoalSalienceAdjustment,
    MemorySalienceSignal,
    ObservedState,
    PredictionError,
    SalienceAssessment,
    SalienceDimension,
    SalienceReasonCode,
    SalienceSignal,
    SalienceSource,
    UserEmphasisSignal,
)


def test_salience_dimension_values():
    assert SalienceDimension.NOVELTY.value == "novelty"
    assert SalienceDimension.URGENCY.value == "urgency"


def test_salience_signal_creation():
    signal = SalienceSignal(
        dimension=SalienceDimension.URGENCY,
        value=0.8,
        confidence=0.9,
        source=SalienceSource.USER_INPUT,
        reason_codes=[SalienceReasonCode.HIGH_URGENCY],
    )
    assert signal.value == 0.8
    assert signal.dimension == SalienceDimension.URGENCY


def test_prediction_error_creation():
    error = PredictionError(
        expected=ExpectedState(description="success", confidence=0.9),
        observed=ObservedState(description="failure", confidence=0.8),
        error_magnitude=0.9,
    )
    assert error.error_magnitude == 0.9


def test_user_emphasis_signal():
    signal = UserEmphasisSignal(emphasis_type="critical", target="x", strength=0.7)
    assert signal.emphasis_type == "critical"
    assert signal.strength == 0.7


def test_memory_salience_signal_tenant():
    ms = MemorySalienceSignal(memory_id="m1", salience_value=0.8, tenant_id="tenant-a")
    assert ms.tenant_id == "tenant-a"


def test_goal_salience_adjustment_tenant():
    ga = GoalSalienceAdjustment(goal_id="g1", adjustment=0.5, tenant_id="tenant-a")
    assert ga.tenant_id == "tenant-a"


def test_salience_assessment_defaults():
    a = SalienceAssessment()
    assert a.overall == 0.0


def test_salience_assessment_computed_overall():
    a = SalienceAssessment(urgency=1.0, risk=0.0, novelty=0.0)
    assert a.overall == pytest.approx(1.0, rel=1e-2)
