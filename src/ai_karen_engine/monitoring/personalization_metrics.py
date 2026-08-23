"""Personalization metrics for KAREN Sprint 2."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class PersonalizationMetrics:
    """Collects personalization metrics."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.evidence_total = self.metrics_manager.register_counter(
                "karen_personalization_evidence_total",
                "Total personalization evidence events processed",
                ["preference_category", "source_type"],
            )
            self.updates_total = self.metrics_manager.register_counter(
                "karen_personalization_updates_total",
                "Total personalization model updates",
                ["preference_category", "status"],
            )
            self.contradictions_total = self.metrics_manager.register_counter(
                "karen_personalization_contradictions_total",
                "Total personalization contradictions detected",
                ["preference_category"],
            )
            self.snapshot_seconds = self.metrics_manager.register_histogram(
                "karen_personalization_snapshot_seconds",
                "Latency of personalization snapshot builds",
                ["status"],
                buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            )

    def record_evidence(
        self,
        preference_category: str,
        source_type: str,
    ) -> None:
        try:
            self.evidence_total.labels(
                preference_category=preference_category,
                source_type=source_type,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record personalization evidence metric: %s", exc)

    def record_update(
        self,
        preference_category: str,
        status: str,
    ) -> None:
        try:
            self.updates_total.labels(
                preference_category=preference_category,
                status=status,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record personalization update metric: %s", exc)

    def record_contradiction(
        self,
        preference_category: str,
    ) -> None:
        try:
            self.contradictions_total.labels(
                preference_category=preference_category,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record personalization contradiction metric: %s", exc)

    def record_snapshot(
        self,
        status: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.snapshot_seconds.labels(status=status).observe(duration_seconds)
        except Exception as exc:
            logger.debug("Failed to record personalization snapshot metric: %s", exc)


_personalization_metrics: Optional[PersonalizationMetrics] = None


def get_personalization_metrics() -> PersonalizationMetrics:
    global _personalization_metrics
    if _personalization_metrics is None:
        _personalization_metrics = PersonalizationMetrics()
    return _personalization_metrics
