"""Adaptive intelligence metrics for KAREN Sprint 3."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class AdaptiveMetrics:
    """Collects adaptive intelligence metrics."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.recommendations_total = self.metrics_manager.register_counter(
                "karen_adaptive_recommendations_total",
                "Total adaptive recommendations produced",
                ["task_type", "execution_path", "status"],
            )
            self.ranking_seconds = self.metrics_manager.register_histogram(
                "karen_adaptive_ranking_seconds",
                "Latency of adaptive ranking",
                ["task_type"],
                buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            )
            self.candidate_count = self.metrics_manager.register_histogram(
                "karen_adaptive_candidate_count",
                "Number of candidates considered by adaptive runtime",
                ["task_type"],
                buckets=[1, 2, 5, 10, 20, 50, 100],
            )
            self.shadow_disagreement_total = self.metrics_manager.register_counter(
                "karen_adaptive_shadow_disagreement_total",
                "Total shadow adaptive disagreements with live policy",
                ["task_type"],
            )
            self.suggestions_total = self.metrics_manager.register_counter(
                "karen_suggestions_total",
                "Total suggestions emitted by suggestion engine",
                ["suggestion_type", "status"],
            )

    def record_recommendation(
        self,
        task_type: str,
        execution_path: str,
        status: str,
    ) -> None:
        try:
            self.recommendations_total.labels(
                task_type=task_type,
                execution_path=execution_path,
                status=status,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record adaptive recommendation metric: %s", exc)

    def record_ranking(
        self,
        task_type: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.ranking_seconds.labels(task_type=task_type).observe(duration_seconds)
        except Exception as exc:
            logger.debug("Failed to record adaptive ranking metric: %s", exc)

    def record_candidate_count(
        self,
        task_type: str,
        count: int,
    ) -> None:
        try:
            self.candidate_count.labels(task_type=task_type).observe(count)
        except Exception as exc:
            logger.debug("Failed to record adaptive candidate count metric: %s", exc)

    def record_shadow_disagreement(
        self,
        task_type: str,
    ) -> None:
        try:
            self.shadow_disagreement_total.labels(task_type=task_type).inc()
        except Exception as exc:
            logger.debug("Failed to record adaptive shadow disagreement metric: %s", exc)

    def record_suggestion(
        self,
        suggestion_type: str,
        status: str,
    ) -> None:
        try:
            self.suggestions_total.labels(
                suggestion_type=suggestion_type,
                status=status,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record suggestion metric: %s", exc)


_adaptive_metrics: Optional[AdaptiveMetrics] = None


def get_adaptive_metrics() -> AdaptiveMetrics:
    global _adaptive_metrics
    if _adaptive_metrics is None:
        _adaptive_metrics = AdaptiveMetrics()
    return _adaptive_metrics
