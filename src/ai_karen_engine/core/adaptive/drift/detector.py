"""Legacy drift detector backends for transitional adaptive evaluation.

These backends are compatibility-only. New production drift detection belongs
under ``core.intelligence.ml``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.adaptive.drift import (
    DriftDetectorBackend,
    DriftSeverity,
    DriftSignal,
    DriftSignalType,
)


@dataclass(slots=True)
class ADWINConfig:
    delta: float = 0.002
    clock: int = 32
    min_bucket_size: int = 5
    grace_period: int = 10


class ADWINBackend(DriftDetectorBackend):
    """Small compatibility ADWIN-style detector.

    This is intentionally conservative and should not be promoted to canonical
    ML drift authority. It returns an explicit signal when its legacy window
    check detects a distribution shift.
    """

    def __init__(self, config: ADWINConfig | None = None) -> None:
        self._config = config or ADWINConfig()
        self._total = 0.0
        self._width = 0
        self._buckets: list[dict[str, Any]] = []
        self._signal_count = 0

    def update(self, value: float) -> DriftSignal | None:
        self._insert(value)
        self._total += value
        self._width += 1

        if self._width < max(self._config.grace_period, self._config.min_bucket_size):
            return None

        if not self._check_drift():
            return None

        self._signal_count += 1
        return DriftSignal(
            signal_id=f"adwin-drift-{self._signal_count}",
            signal_type=DriftSignalType.POLICY_PERFORMANCE_DRIFT,
            detector="adwin_compat",
            detector_version="legacy-v1",
            metric="performance",
            severity=DriftSeverity.MEDIUM,
            confidence=0.7,
            metadata={"compatibility_only": True},
        )

    def _insert(self, value: float) -> None:
        self._buckets.append({"total": value, "width": 1})

    def _check_drift(self) -> bool:
        if self._width < self._config.min_bucket_size * 2:
            return False

        split = self._width // 2
        left = self._buckets[:split]
        right = self._buckets[split:]
        if not left or not right:
            return False

        left_mean = sum(bucket["total"] for bucket in left) / len(left)
        right_mean = sum(bucket["total"] for bucket in right) / len(right)
        n = min(len(left), len(right))
        epsilon = math.sqrt(max(0.0, math.log(2.0 / self._config.delta) / (2.0 * n)))
        if abs(left_mean - right_mean) < epsilon:
            return False

        self._buckets = right
        self._width = len(right)
        self._total = sum(bucket["total"] for bucket in right)
        return True

    def reset(self) -> None:
        self._total = 0.0
        self._width = 0
        self._buckets = []


@dataclass(slots=True)
class PageHinkleyConfig:
    threshold: float = 0.5
    alpha: float = 0.001
    min_samples: int = 30
    grace_period: int = 30


class PageHinkleyBackend(DriftDetectorBackend):
    """Compatibility Page-Hinkley detector with explicit configured threshold."""

    def __init__(self, config: PageHinkleyConfig | None = None) -> None:
        self._config = config or PageHinkleyConfig()
        self._mean = 0.0
        self._sample_count = 0
        self._cumulative = 0.0
        self._min_cumulative = 0.0
        self._signal_count = 0

    def update(self, value: float) -> DriftSignal | None:
        self._sample_count += 1
        previous_mean = self._mean
        self._mean += (value - self._mean) / self._sample_count
        self._cumulative += value - previous_mean - self._config.alpha
        self._min_cumulative = min(self._min_cumulative, self._cumulative)

        if self._sample_count <= max(self._config.min_samples, self._config.grace_period):
            return None

        if self._cumulative - self._min_cumulative <= self._config.threshold:
            return None

        self._signal_count += 1
        signal = DriftSignal(
            signal_id=f"page-hinkley-drift-{self._signal_count}",
            signal_type=DriftSignalType.POLICY_PERFORMANCE_DRIFT,
            detector="page_hinkley_compat",
            detector_version="legacy-v1",
            metric="performance",
            severity=DriftSeverity.MEDIUM,
            confidence=0.8,
            metadata={"compatibility_only": True},
        )
        self.reset()
        return signal

    def reset(self) -> None:
        self._mean = 0.0
        self._sample_count = 0
        self._cumulative = 0.0
        self._min_cumulative = 0.0


__all__ = [
    "ADWINBackend",
    "ADWINConfig",
    "PageHinkleyBackend",
    "PageHinkleyConfig",
]
