"""ML inference metrics for KAREN intelligence sprints."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class MLMetrics:
    """Collects ML inference and fallback metrics."""

    def __init__(self) -> None:
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()

    def _initialize_metrics(self) -> None:
        with self.metrics_manager.safe_metrics_context():
            self.inference_seconds = self.metrics_manager.register_histogram(
                "karen_ml_inference_seconds",
                "ML inference latency in seconds",
                ["prediction_task", "model_id", "model_version", "status"],
                buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            )
            self.predictions_total = self.metrics_manager.register_counter(
                "karen_ml_predictions_total",
                "Total ML predictions served",
                ["prediction_task", "model_id", "model_version", "status"],
            )
            self.fallback_total = self.metrics_manager.register_counter(
                "karen_ml_fallback_total",
                "Total ML fallback events",
                ["prediction_task", "model_id", "fallback_reason"],
            )
            self.model_load_failures_total = self.metrics_manager.register_counter(
                "karen_ml_model_load_failures_total",
                "Total ML model load failures",
                ["model_id", "error_type"],
            )
            self.shadow_disagreement_total = self.metrics_manager.register_counter(
                "karen_ml_shadow_disagreement_total",
                "Total shadow model disagreements with primary",
                ["model_id", "model_version", "prediction_task"],
            )
            self.calibration_error = self.metrics_manager.register_histogram(
                "karen_ml_calibration_error",
                "ML model calibration error (ECE)",
                ["model_id", "model_version", "prediction_task"],
                buckets=[0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5],
            )
            self.evaluation_score = self.metrics_manager.register_gauge(
                "karen_ml_evaluation_score",
                "ML model evaluation score (F1/accuracy)",
                ["model_id", "model_version", "prediction_task", "metric"],
            )
            self.promotion_status = self.metrics_manager.register_gauge(
                "karen_ml_promotion_status",
                "ML model promotion status (1=eligible, 0=blocked, -1=insufficient)",
                ["model_id", "model_version", "purpose"],
            )

    def record_inference(
        self,
        prediction_task: str,
        model_id: str,
        model_version: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        try:
            self.inference_seconds.labels(
                prediction_task=prediction_task,
                model_id=model_id,
                model_version=model_version,
                status=status,
            ).observe(duration_seconds)
            self.predictions_total.labels(
                prediction_task=prediction_task,
                model_id=model_id,
                model_version=model_version,
                status=status,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record ML inference metric: %s", exc)

    def record_fallback(
        self,
        prediction_task: str,
        model_id: str,
        fallback_reason: str,
    ) -> None:
        try:
            self.fallback_total.labels(
                prediction_task=prediction_task,
                model_id=model_id,
                fallback_reason=fallback_reason,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record ML fallback metric: %s", exc)

    def record_model_load_failure(self, model_id: str, error_type: str) -> None:
        try:
            self.model_load_failures_total.labels(
                model_id=model_id, error_type=error_type
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record model load failure metric: %s", exc)

    def record_shadow_disagreement(
        self,
        model_id: str,
        model_version: str,
        prediction_task: str,
    ) -> None:
        try:
            self.shadow_disagreement_total.labels(
                model_id=model_id,
                model_version=model_version,
                prediction_task=prediction_task,
            ).inc()
        except Exception as exc:
            logger.debug("Failed to record shadow disagreement metric: %s", exc)

    def record_calibration_error(
        self,
        model_id: str,
        model_version: str,
        prediction_task: str,
        ece: float,
    ) -> None:
        try:
            self.calibration_error.labels(
                model_id=model_id,
                model_version=model_version,
                prediction_task=prediction_task,
            ).observe(ece)
        except Exception as exc:
            logger.debug("Failed to record calibration error metric: %s", exc)

    def record_evaluation_score(
        self,
        model_id: str,
        model_version: str,
        prediction_task: str,
        metric: str,
        value: float,
    ) -> None:
        try:
            self.evaluation_score.labels(
                model_id=model_id,
                model_version=model_version,
                prediction_task=prediction_task,
                metric=metric,
            ).set(value)
        except Exception as exc:
            logger.debug("Failed to record evaluation score metric: %s", exc)

    def record_promotion_status(
        self,
        model_id: str,
        model_version: str,
        purpose: str,
        decision: str,
    ) -> None:
        try:
            value = {"PROMOTION_ELIGIBLE": 1.0, "PROMOTION_BLOCKED": 0.0, "INSUFFICIENT_EVIDENCE": -1.0}.get(decision, -1.0)
            self.promotion_status.labels(
                model_id=model_id,
                model_version=model_version,
                purpose=purpose,
            ).set(value)
        except Exception as exc:
            logger.debug("Failed to record promotion status metric: %s", exc)


_ml_metrics: Optional[MLMetrics] = None


def get_ml_metrics() -> MLMetrics:
    global _ml_metrics
    if _ml_metrics is None:
        _ml_metrics = MLMetrics()
    return _ml_metrics
