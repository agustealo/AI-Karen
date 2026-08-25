from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.reasoning.meta.contracts import (
    CalibrationObservation,
    MetaReasonCode,
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

    def accuracy(self) -> float:
        if not self._observations:
            return 0.0
        correct = sum(1 for o in self._observations if not o.correction_required)
        return correct / len(self._observations)
