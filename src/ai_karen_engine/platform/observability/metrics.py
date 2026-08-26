from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from .contracts import HIGH_CARDINALITY_LABELS


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class CardinalityError(ValueError):
    """Raised when a metric label would exceed the bounded label vocabulary."""


class _LabeledMetric:
    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        self.name = name
        self.description = description
        self.label_names = label_names

    def _label_key(self, kwargs: Mapping[str, str]) -> tuple[str, ...]:
        expected = set(self.label_names)
        supplied = set(kwargs)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            details: list[str] = []
            if missing:
                details.append(f"missing={missing}")
            if extra:
                details.append(f"extra={extra}")
            raise ValueError(
                f"Metric '{self.name}' label mismatch: {', '.join(details) or 'unknown'}"
            )
        return tuple(str(kwargs[label]) for label in self.label_names)


class _Counter(_LabeledMetric):
    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        super().__init__(name, description, label_names)
        self._values: dict[tuple[str, ...], float] = {}

    def labels(self, **kwargs: str) -> _BoundCounter:
        return _BoundCounter(self, self._label_key(kwargs))

    def _inc(self, key: tuple[str, ...], amount: float) -> None:
        self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **kwargs: str) -> float:
        key = self._label_key(kwargs)
        return self._values.get(key, 0.0)

    def collect(self) -> dict[tuple[str, ...], float]:
        return dict(self._values)


class _BoundCounter:
    def __init__(self, counter: _Counter, label_values: tuple[str, ...]) -> None:
        self._counter = counter
        self._label_values = label_values

    def inc(self, amount: float = 1.0) -> None:
        self._counter._inc(self._label_values, amount)


class _Gauge(_LabeledMetric):
    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        super().__init__(name, description, label_names)
        self._values: dict[tuple[str, ...], float] = {}

    def labels(self, **kwargs: str) -> _BoundGauge:
        return _BoundGauge(self, self._label_key(kwargs))

    def _set(self, key: tuple[str, ...], value: float) -> None:
        self._values[key] = value

    def _inc(self, key: tuple[str, ...], amount: float) -> None:
        self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **kwargs: str) -> float:
        key = self._label_key(kwargs)
        return self._values.get(key, 0.0)

    def collect(self) -> dict[tuple[str, ...], float]:
        return dict(self._values)


class _BoundGauge:
    def __init__(self, gauge: _Gauge, label_values: tuple[str, ...]) -> None:
        self._gauge = gauge
        self._label_values = label_values

    def set(self, value: float) -> None:
        self._gauge._set(self._label_values, value)

    def inc(self, amount: float = 1.0) -> None:
        self._gauge._inc(self._label_values, amount)

    def dec(self, amount: float = 1.0) -> None:
        self._gauge._inc(self._label_values, -amount)


class _Histogram(_LabeledMetric):
    def __init__(
        self,
        name: str,
        description: str,
        label_names: tuple[str, ...],
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        super().__init__(name, description, label_names)
        self.buckets = buckets or (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
        self._values: dict[tuple[str, ...], list[float]] = {}

    def labels(self, **kwargs: str) -> _BoundHistogram:
        return _BoundHistogram(self, self._label_key(kwargs))

    def _observe(self, key: tuple[str, ...], value: float) -> None:
        self._values.setdefault(key, []).append(value)

    def collect(self) -> dict[tuple[str, ...], list[float]]:
        return {key: list(values) for key, values in self._values.items()}


class _BoundHistogram:
    def __init__(self, histogram: _Histogram, label_values: tuple[str, ...]) -> None:
        self._histogram = histogram
        self._label_values = label_values

    def observe(self, value: float) -> None:
        self._histogram._observe(self._label_values, value)


class MetricsCollector:
    """Canonical, local-first metrics collector.

    Centralizes metric names and enforces a bounded label vocabulary so that
    high-cardinality identifiers (user_id, request_id, raw prompts, URLs) are
    never promoted to metric labels. Works with zero external telemetry
    infrastructure; adapters may expose the same collector to Prometheus or
    other monitoring systems without becoming a second metrics authority.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, _Counter] = {}
        self._gauges: dict[str, _Gauge] = {}
        self._histograms: dict[str, _Histogram] = {}

    @staticmethod
    def _validate_labels(label_names: Sequence[str]) -> tuple[str, ...]:
        for label in label_names:
            if label in HIGH_CARDINALITY_LABELS:
                raise CardinalityError(
                    f"Metric label '{label}' is high-cardinality and must not be "
                    "used as a label. Record it in structured event metadata instead."
                )
        return tuple(label_names)

    def counter(
        self,
        name: str,
        description: str,
        label_names: Sequence[str] = (),
    ) -> _Counter:
        labels = self._validate_labels(label_names)
        with self._lock:
            if name not in self._counters:
                self._counters[name] = _Counter(name, description, labels)
            return self._counters[name]

    def gauge(
        self,
        name: str,
        description: str,
        label_names: Sequence[str] = (),
    ) -> _Gauge:
        labels = self._validate_labels(label_names)
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = _Gauge(name, description, labels)
            return self._gauges[name]

    def histogram(
        self,
        name: str,
        description: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] | None = None,
    ) -> _Histogram:
        labels = self._validate_labels(label_names)
        bucket_tuple = tuple(buckets) if buckets is not None else None
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = _Histogram(name, description, labels, bucket_tuple)
            return self._histograms[name]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": {
                    name: {
                        "description": counter.description,
                        "label_names": counter.label_names,
                        "values": counter.collect(),
                    }
                    for name, counter in self._counters.items()
                },
                "gauges": {
                    name: {
                        "description": gauge.description,
                        "label_names": gauge.label_names,
                        "values": gauge.collect(),
                    }
                    for name, gauge in self._gauges.items()
                },
                "histograms": {
                    name: {
                        "description": histogram.description,
                        "label_names": histogram.label_names,
                        "buckets": histogram.buckets,
                        "values": histogram.collect(),
                    }
                    for name, histogram in self._histograms.items()
                },
            }


_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Return the process-wide canonical metrics collector singleton."""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector
