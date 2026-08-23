"""Runtime metrics for KAREN API and system health."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class RuntimeMetrics:
    """Collects runtime metrics for the KAREN API."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.requests_total = self.metrics_manager.register_counter(
                "karen_requests_total",
                "Total HTTP requests processed by KAREN",
                ["method", "endpoint", "status"],
            )
            self.request_duration_seconds = self.metrics_manager.register_histogram(
                "karen_request_duration_seconds",
                "HTTP request latency in seconds",
                ["method", "endpoint"],
                buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            )
            self.requests_inflight = self.metrics_manager.register_gauge(
                "karen_requests_inflight",
                "Current number of in-flight HTTP requests",
                ["method", "endpoint"],
            )
            self.degraded_requests_total = self.metrics_manager.register_counter(
                "karen_degraded_requests_total",
                "Total requests served in degraded mode",
                ["reason"],
            )

    def record_request(
        self,
        method: str,
        endpoint: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.requests_total.labels(
                method=method, endpoint=endpoint, status=status
            ).inc()
            self.request_duration_seconds.labels(
                method=method, endpoint=endpoint
            ).observe(duration_seconds)
        except Exception as exc:
            logger.debug("Failed to record request metric: %s", exc)

    def inc_inflight(self, method: str, endpoint: str) -> None:
        try:
            self.requests_inflight.labels(method=method, endpoint=endpoint).inc()
        except Exception as exc:
            logger.debug("Failed to inc inflight metric: %s", exc)

    def dec_inflight(self, method: str, endpoint: str) -> None:
        try:
            self.requests_inflight.labels(method=method, endpoint=endpoint).dec()
        except Exception as exc:
            logger.debug("Failed to dec inflight metric: %s", exc)

    def record_degraded(self, reason: str) -> None:
        try:
            self.degraded_requests_total.labels(reason=reason).inc()
        except Exception as exc:
            logger.debug("Failed to record degraded metric: %s", exc)


_runtime_metrics: Optional[RuntimeMetrics] = None


def get_runtime_metrics() -> RuntimeMetrics:
    global _runtime_metrics
    if _runtime_metrics is None:
        _runtime_metrics = RuntimeMetrics()
    return _runtime_metrics
