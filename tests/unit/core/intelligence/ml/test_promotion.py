from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkResult, MetricResult
from ai_karen_engine.core.intelligence.ml.promotion import PromotionDecision, evaluate_promotion


def _make_result(model_id: str, f1: float, fallback: float, latency_p95: float, ece: float, errors: int, samples: int = 100):
    metrics = {
        "accuracy": MetricResult("accuracy", f1, samples),
        "macro_f1": MetricResult("macro_f1", f1, samples),
        "fallback_rate": MetricResult("fallback_rate", fallback, samples),
        "ece": MetricResult("ece", ece, samples),
        "brier_score": MetricResult("brier_score", 0.1, samples),
    }
    return BenchmarkResult(
        model_id=model_id,
        model_version="v1",
        task=PredictionTask.INTENT,
        dataset_version="ml-eval-v1",
        sample_count=samples,
        metrics=metrics,
        latency_p50_ms=10.0,
        latency_p95_ms=latency_p95,
        error_count=errors,
        fallback_count=int(fallback * samples),
        abstention_count=0,
    )


def test_promotion_eligible_when_better():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.02, errors=0)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_ELIGIBLE


def test_promotion_blocked_insufficient_gain():
    candidate = _make_result("candidate", f1=0.80, fallback=0.1, latency_p95=200.0, ece=0.02, errors=0)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_BLOCKED
    assert any("F1" in r for r in reasons)


def test_promotion_blocked_higher_fallback():
    candidate = _make_result("candidate", f1=0.85, fallback=0.3, latency_p95=200.0, ece=0.02, errors=0)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_BLOCKED
    assert any("fallback" in r.lower() for r in reasons)


def test_promotion_blocked_high_latency():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=600.0, ece=0.02, errors=0)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_BLOCKED
    assert any("latency" in r.lower() for r in reasons)


def test_promotion_blocked_high_ece():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.10, errors=0)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_BLOCKED
    assert any("ECE" in r for r in reasons)


def test_promotion_blocked_errors():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.02, errors=1)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.PROMOTION_BLOCKED
    assert any("errors" in r.lower() for r in reasons)


def test_promotion_insufficient_samples():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.02, errors=0, samples=10)
    active = _make_result("active", f1=0.80, fallback=0.2, latency_p95=300.0, ece=0.03, errors=0, samples=100)
    decision, reasons = evaluate_promotion(candidate, active)
    assert decision == PromotionDecision.INSUFFICIENT_EVIDENCE


def test_promotion_insufficient_samples_no_active():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.02, errors=0, samples=10)
    decision, reasons = evaluate_promotion(candidate)
    assert decision == PromotionDecision.INSUFFICIENT_EVIDENCE


def test_promotion_eligible_no_active_sufficient_samples():
    candidate = _make_result("candidate", f1=0.85, fallback=0.1, latency_p95=200.0, ece=0.02, errors=0, samples=100)
    decision, reasons = evaluate_promotion(candidate)
    assert decision == PromotionDecision.PROMOTION_ELIGIBLE
