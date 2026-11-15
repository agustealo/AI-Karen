from __future__ import annotations

import logging

from ai_karen_engine.core.reasoning.meta.contracts import (
    CalibrationObservation,
)

logger = logging.getLogger(__name__)


class CalibrationTracker:
    """Tracks calibration observations for later learning."""

    def __init__(self) -> None:
        self._observations: list[CalibrationObservation] = []

    def record(self, observation: CalibrationObservation) -> None:
        self._observations.append(observation)

    def observations(self) -> list[CalibrationObservation]:
        return list(self._observations)

    def correction_free_rate(self) -> float | None:
        """Observational correction-free fraction, NOT verified model accuracy."""
        if not self._observations:
            return None
        without_correction = sum(
            1 for observation in self._observations
            if not observation.correction_required
        )
        return without_correction / len(self._observations)

    def accuracy(self) -> float:
        """Legacy compatibility: correction-free rate, not calibrated accuracy.

        Existing callers retain the historical return contract. This method
        must not be used to promote a model or report calibrated confidence.
        """
        rate = self.correction_free_rate()
        return rate if rate is not None else 0.0
