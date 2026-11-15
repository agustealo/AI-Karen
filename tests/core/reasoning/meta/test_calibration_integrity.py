"""KCOG-00B1: missing evidence cannot be reported as perfect calibration."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.reasoning.meta.calibration import CalibrationTracker
from ai_karen_engine.core.reasoning.meta.contracts import CalibrationObservation


def test_missing_target_never_becomes_zero_calibration_error() -> None:
    observation = CalibrationObservation(predicted_confidence=0.98)

    assert observation.calibration_error() is None
    assert not observation.is_well_calibrated()


def test_recorded_target_discrepancy_is_not_population_calibration() -> None:
    observation = CalibrationObservation(
        predicted_confidence=0.8,
        actual_confidence=0.5,
    )

    assert observation.calibration_error() == pytest.approx(0.3)
    assert not observation.is_well_calibrated(tolerance=0.2)


def test_tracker_explicitly_names_unverified_correction_fraction() -> None:
    tracker = CalibrationTracker()
    assert tracker.correction_free_rate() is None

    tracker.record(CalibrationObservation(
        predicted_confidence=0.9, correction_required=False,
    ))
    tracker.record(CalibrationObservation(
        predicted_confidence=0.8, correction_required=True,
    ))

    assert tracker.correction_free_rate() == pytest.approx(0.5)
    # Legacy API is retained but must not be interpreted as ML calibration.
    assert tracker.accuracy() == pytest.approx(0.5)
