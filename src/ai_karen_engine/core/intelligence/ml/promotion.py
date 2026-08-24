from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from ai_karen_engine.config.config_manager import (
    get_ml_promotion_max_ece,
    get_ml_promotion_max_latency_ms,
    get_ml_promotion_min_gain,
    get_ml_promotion_min_samples,
)
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkResult, MetricResult

logger = logging.getLogger(__name__)


class PromotionDecision(str, Enum):
    PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PromotionGateError(Exception):
    """Raised when promotion evaluation cannot be completed."""


def evaluate_promotion(
    candidate: BenchmarkResult,
    active: BenchmarkResult | None = None,
) -> tuple[PromotionDecision, list[str]]:
    reasons: list[str] = []

    if active is None:
        if candidate.sample_count < get_ml_promotion_min_samples():
            return PromotionDecision.INSUFFICIENT_EVIDENCE, ["No active model to compare against"]
        f1 = _primary_metric(candidate)
        if f1 is None:
            return PromotionDecision.INSUFFICIENT_EVIDENCE, ["Missing primary metric for standalone evaluation"]
        if candidate.sample_count >= get_ml_promotion_min_samples():
            return PromotionDecision.PROMOTION_ELIGIBLE, ["Sufficient standalone evidence"]
        return PromotionDecision.INSUFFICIENT_EVIDENCE, ["Insufficient standalone samples"]

    if candidate.sample_count < get_ml_promotion_min_samples():
        reasons.append(f"Candidate samples {candidate.sample_count} < {get_ml_promotion_min_samples()}")
        return PromotionDecision.INSUFFICIENT_EVIDENCE, reasons

    candidate_f1 = _primary_metric(candidate)
    active_f1 = _primary_metric(active)
    if candidate_f1 is None or active_f1 is None:
        reasons.append("Missing F1 metric for comparison")
        return PromotionDecision.INSUFFICIENT_EVIDENCE, reasons

    min_gain = get_ml_promotion_min_gain()
    if candidate_f1.value < active_f1.value + min_gain:
        reasons.append(
            f"Candidate F1 {candidate_f1.value:.4f} < active F1 {active_f1.value:.4f} + {min_gain:.4f}"
        )

    candidate_fallback = candidate.metrics.get("fallback_rate")
    active_fallback = active.metrics.get("fallback_rate")
    if candidate_fallback is not None and active_fallback is not None:
        if candidate_fallback.value > active_fallback.value:
            reasons.append(
                f"Candidate fallback rate {candidate_fallback.value:.4f} > active {active_fallback.value:.4f}"
            )

    max_latency = get_ml_promotion_max_latency_ms()
    if candidate.latency_p95_ms > max_latency:
        reasons.append(f"Candidate p95 latency {candidate.latency_p95_ms:.2f}ms > {max_latency:.2f}ms")

    max_ece = get_ml_promotion_max_ece()
    candidate_ece = candidate.metrics.get("ece")
    if candidate_ece is not None and candidate_ece.value > max_ece:
        reasons.append(f"Candidate ECE {candidate_ece.value:.4f} > {max_ece:.4f}")

    if candidate.error_count > 0:
        reasons.append(f"Candidate has {candidate.error_count} errors")

    if reasons:
        return PromotionDecision.PROMOTION_BLOCKED, reasons

    return PromotionDecision.PROMOTION_ELIGIBLE, []


def _primary_metric(result: BenchmarkResult) -> MetricResult | None:
    if result.task == PredictionTask.CAPABILITY:
        return result.metrics.get("micro_f1") or result.metrics.get("macro_f1")
    return result.metrics.get("accuracy") or result.metrics.get("macro_f1")
