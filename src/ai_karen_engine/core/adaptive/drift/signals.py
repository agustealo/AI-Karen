"""Drift signal record and adapter utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.adaptive.drift import DriftDetectorBackend, DriftSeverity, DriftSignal, DriftSignalType


@dataclass(slots=True)
class DriftRecord:
    signal_id: str
    signal_type: DriftSignalType
    detector: str
    detector_version: str
    metric: str
    previous_distribution: dict[str, Any]
    current_distribution: dict[str, Any]
    severity: DriftSeverity
    confidence: float
    window_start: str
    window_end: str
    affected_policy: str
    metadata: dict[str, Any]


def record_from_signal(signal: DriftSignal) -> DriftRecord:
    return DriftRecord(
        signal_id=signal.signal_id,
        signal_type=signal.signal_type,
        detector=signal.detector,
        detector_version=signal.detector_version,
        metric=signal.metric,
        previous_distribution=dict(signal.previous_distribution),
        current_distribution=dict(signal.current_distribution),
        severity=signal.severity,
        confidence=signal.confidence,
        window_start=signal.window_start,
        window_end=signal.window_end,
        affected_policy=signal.affected_policy,
        metadata=dict(signal.metadata),
    )
