"""Legacy adaptive drift contracts.

This package is transitional and is not a production drift authority. Model
quality, calibration, outcome aggregation, retraining triggers, and future
canonical drift detection belong under ``core.intelligence.ml``.

Do not add new drift detectors or promotion gates here. Existing contracts are
kept only while off-policy adaptive-learning consumers migrate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DriftSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DriftSignalType(str, Enum):
    POLICY_REWARD_DRIFT = "policy_reward_drift"
    ACTION_DISTRIBUTION_DRIFT = "action_distribution_drift"
    POLICY_PERFORMANCE_DRIFT = "policy_performance_drift"


class DriftStatus(str, Enum):
    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class DriftSignal:
    signal_id: str
    signal_type: DriftSignalType
    detector: str
    detector_version: str
    metric: str
    previous_distribution: dict[str, Any] = field(default_factory=dict)
    current_distribution: dict[str, Any] = field(default_factory=dict)
    severity: DriftSeverity = DriftSeverity.LOW
    confidence: float = 0.0
    window_start: str = ""
    window_end: str = ""
    affected_policy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DriftDetectorBackend(ABC):
    @abstractmethod
    def update(self, value: float) -> DriftSignal | None:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError


class DriftMonitor:
    """Compatibility monitor for legacy off-policy evaluation only."""

    def __init__(self, backend: DriftDetectorBackend | None = None) -> None:
        self._backend = backend
        self._signals: list[DriftSignal] = []

    def update(self, value: float, policy_id: str) -> DriftSignal | None:
        if self._backend is None:
            return None
        signal = self._backend.update(value)
        if signal is not None:
            signal.affected_policy = policy_id
            self._signals.append(signal)
        return signal

    def signals(self) -> list[DriftSignal]:
        return list(self._signals)

    def status(self) -> DriftStatus:
        if not self._signals:
            return DriftStatus.NONE
        severities = [signal.severity for signal in self._signals]
        if DriftSeverity.CRITICAL in severities or DriftSeverity.HIGH in severities:
            return DriftStatus.CRITICAL
        if DriftSeverity.MEDIUM in severities:
            return DriftStatus.WARNING
        return DriftStatus.NONE


__all__ = [
    "DriftDetectorBackend",
    "DriftMonitor",
    "DriftSeverity",
    "DriftSignal",
    "DriftSignalType",
    "DriftStatus",
]
