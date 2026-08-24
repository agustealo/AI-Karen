"""Concrete drift detector backend implementations.

Lightweight ADWIN and Page-Hinkley implementations behind DriftDetectorBackend.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.adaptive.drift import (
    DriftDetectorBackend,
    DriftMonitor,
    DriftSeverity,
    DriftSignal,
    DriftSignalType,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ADWINConfig:
    delta: float = 0.002
    clock: int = 32
    min_bucket_size: int = 5
    grace_period: int = 10


class ADWINBackend(DriftDetectorBackend):
    def __init__(self, config: ADWINConfig | None = None) -> None:
        self._config = config or ADWINConfig()
        self._total = 0.0
        self._width = 0
        self._variance = 0.0
        self._reset_cutoff: int = 0
        self._bucket_0_total: float = 0.0
        self._bucket_0_width: int = 0
        self._bucket_0_variance: float = 0.0
        self._buckets: list[dict[str, Any]] = []

    def update(self, value: float) -> DriftSignal | None:
        self._insert(value)
        self._total += value
        self._width += 1
        reduced = False
        while self._width > self._config.min_bucket_size:
            if self._check_drift():
                self._compress()
                reduced = True
            if not reduced:
                break
        return None

    def _insert(self, value: float) -> None:
        self._buckets.append({
            "total": value,
            "width": 1,
            "variance": 0.0,
        })

    def _check_drift(self) -> bool:
        if self._width < self._config.min_bucket_size:
            return False
        n0 = 1
        n1 = self._width - n0
        if n1 < self._config.min_bucket_size:
            return False
        mu0 = self._buckets[0]["total"] / max(self._buckets[0]["width"], 1)
        mu1 = (self._total - self._buckets[0]["total"]) / max(n1, 1)
        eps = math.sqrt(
            (2.0 * math.log(2.0 * self._width / self._config.delta)) / n1
        ) + (2.0 / n1) * math.log(3.0 * self._width / self._config.delta)
        if abs(mu0 - mu1) >= eps:
            self._buckets = self._buckets[1:]
            self._width -= 1
            self._total -= mu0
            return True
        return False

    def _compress(self) -> None:
        pass

    def reset(self) -> None:
        self._total = 0.0
        self._width = 0
        self._variance = 0.0
        self._buckets = []


@dataclass(slots=True)
class PageHinkleyConfig:
    threshold: float = 0.5
    alpha: float = 0.001
    min_samples: int = 30
    grace_period: int = 30


class PageHinkleyBackend(DriftDetectorBackend):
    def __init__(self, config: PageHinkleyConfig | None = None) -> None:
        self._config = config or PageHinkleyConfig()
        self._mean = 0.0
        self._sample_count = 0
        self._sum = 0.0
        self._min_cumsum = 0.0

    def update(self, value: float) -> DriftSignal | None:
        self._sample_count += 1
        self._sum += value - self._mean
        self._mean += (value - self._mean) / self._sample_count
        if self._sum < self._min_cumsum:
            self._min_cumsum = self._sum
        diff = self._sum - self._min_cumsum
        if diff > self._threshold and self._sample_count > self._config.min_samples:
            signal = DriftSignal(
                signal_id=f"drift-{self._sample_count}",
                signal_type=DriftSignalType.POLICY_PERFORMANCE_DRIFT,
                detector="page_hinkley",
                detector_version="v1",
                metric="performance",
                severity=DriftSeverity.MEDIUM,
                confidence=0.8,
                window_start="",
                window_end="",
            )
            self.reset()
            return signal
        return None

    def reset(self) -> None:
        self._mean = 0.0
        self._sample_count = 0
        self._sum = 0.0
        self._min_cumsum = 0.0
