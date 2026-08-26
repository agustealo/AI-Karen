"""Canonical Prometheus metric registration for platform monitoring.

This module owns the small registration surface used by legacy monitoring
collectors. It deliberately lives under ``monitoring`` rather than reviving the
retired ``core.observability`` package.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterable, Iterator, Sequence

from prometheus_client import Counter, Gauge, Histogram


class PrometheusMetricsManager:
    """Register and reuse process-wide Prometheus collectors safely."""

    def __init__(self) -> None:
        self._collectors: dict[tuple[str, str], object] = {}
        self._lock = Lock()

    @contextmanager
    def safe_metrics_context(self) -> Iterator[None]:
        """Compatibility context for collectors that batch registration."""
        yield

    def register_counter(
        self,
        name: str,
        documentation: str,
        labelnames: Iterable[str] = (),
    ) -> Counter:
        return self._register("counter", name, documentation, labelnames)

    def register_gauge(
        self,
        name: str,
        documentation: str,
        labelnames: Iterable[str] = (),
    ) -> Gauge:
        return self._register("gauge", name, documentation, labelnames)

    def register_histogram(
        self,
        name: str,
        documentation: str,
        labelnames: Iterable[str] = (),
        *,
        buckets: Sequence[float] | None = None,
    ) -> Histogram:
        return self._register(
            "histogram",
            name,
            documentation,
            labelnames,
            buckets=buckets,
        )

    def _register(
        self,
        metric_type: str,
        name: str,
        documentation: str,
        labelnames: Iterable[str],
        *,
        buckets: Sequence[float] | None = None,
    ):
        key = (metric_type, name)
        labels = tuple(labelnames)
        with self._lock:
            existing = self._collectors.get(key)
            if existing is not None:
                return existing

            if metric_type == "counter":
                collector = Counter(name, documentation, labels)
            elif metric_type == "gauge":
                collector = Gauge(name, documentation, labels)
            elif metric_type == "histogram":
                kwargs = {"buckets": tuple(buckets)} if buckets is not None else {}
                collector = Histogram(name, documentation, labels, **kwargs)
            else:  # pragma: no cover - internal invariant
                raise ValueError(f"Unsupported metric type: {metric_type}")

            self._collectors[key] = collector
            return collector


_METRICS_MANAGER = PrometheusMetricsManager()


def get_metrics_manager() -> PrometheusMetricsManager:
    """Return the canonical process-wide Prometheus registration manager."""
    return _METRICS_MANAGER
