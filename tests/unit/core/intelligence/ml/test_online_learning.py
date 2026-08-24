from __future__ import annotations

import time

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.online_learning import (
    AdaptiveLayer,
    AdaptiveThresholds,
    MLEvidenceAggregator,
    MLOutcomeCollector,
    MLOutcomeRecord,
)


def _make_outcome(model_id: str, correct: bool, latency: float = 10.0, calibration_error: float = 0.02, fallback: bool = False):
    return MLOutcomeRecord(
        outcome_id=f"o-{time.time()}",
        task=PredictionTask.INTENT,
        model_id=model_id,
        model_version="v1",
        feature_version="v1",
        predicted_label="a",
        expected_label="a" if correct else "b",
        correct=correct,
        raw_probability=0.9,
        calibrated_probability=0.9,
        confidence=0.9,
        latency_ms=latency,
        fallback_used=fallback,
        calibration_error=calibration_error,
    )


def test_outcome_collector_record_and_query():
    collector = MLOutcomeCollector()
    o1 = _make_outcome("m1", True)
    o2 = _make_outcome("m1", False)
    collector.record(o1)
    collector.record(o2)
    assert len(collector.recent(limit=1)) == 1
    assert len(collector.get_outcomes(model_id="m1")) == 2
    assert len(collector.get_outcomes(task=PredictionTask.DOMAIN)) == 0


def test_outcome_collector_clear():
    collector = MLOutcomeCollector()
    collector.record(_make_outcome("m1", True))
    collector.clear()
    assert len(collector.recent()) == 0


def test_evidence_aggregator_basic():
    aggregator = MLEvidenceAggregator()
    o1 = _make_outcome("m1", True, latency=10.0)
    o2 = _make_outcome("m1", False, latency=20.0)
    aggregator.add_outcome(o1)
    aggregator.add_outcome(o2)
    profile = aggregator.get_profile("m1", "v1", PredictionTask.INTENT)
    assert profile is not None
    assert profile.sample_count == 2
    assert profile.correct_count == 1
    assert profile.accuracy == 0.5
    assert profile.avg_latency_ms == 15.0


def test_evidence_aggregator_decay():
    aggregator = MLEvidenceAggregator()
    o = _make_outcome("m1", True)
    o.timestamp = str(time.time() - 999999)
    aggregator.add_outcome(o)
    aggregator.decay_older_than(86400)
    assert len(aggregator.all_profiles()) == 0


def test_adaptive_layer_record_and_adapt():
    layer = AdaptiveLayer()
    for i in range(30):
        layer.record_outcome(_make_outcome("m1", correct=(i % 2 == 0), latency=10.0 + i))
    thresholds = layer.adapt_thresholds()
    assert thresholds.confidence_threshold > 0.0
    assert thresholds.latency_threshold_ms > 0.0


def test_adaptive_layer_should_promote():
    layer = AdaptiveLayer()
    for i in range(30):
        layer.record_outcome(_make_outcome("active", correct=(i % 3 != 0), latency=10.0))
    for i in range(30):
        layer.record_outcome(_make_outcome("candidate", correct=True, latency=5.0))
    promote, reason = layer.should_promote_candidate("candidate", "v1", PredictionTask.INTENT, "active", "v1")
    assert promote is True
    assert reason == "promotion_eligible"


def test_adaptive_layer_should_not_promote_inferior():
    layer = AdaptiveLayer()
    for i in range(30):
        layer.record_outcome(_make_outcome("active", correct=True, latency=10.0))
    for i in range(30):
        layer.record_outcome(_make_outcome("candidate", correct=False, latency=5.0))
    promote, reason = layer.should_promote_candidate("candidate", "v1", PredictionTask.INTENT, "active", "v1")
    assert promote is False
    assert "not_more_accurate" in reason


def test_adaptive_layer_insufficient_evidence():
    layer = AdaptiveLayer()
    for i in range(5):
        layer.record_outcome(_make_outcome("candidate", correct=True, latency=5.0))
    promote, reason = layer.should_promote_candidate("candidate", "v1", PredictionTask.INTENT, "active", "v1")
    assert promote is False
    assert "insufficient" in reason


def test_adaptive_thresholds_defaults():
    t = AdaptiveThresholds()
    assert t.confidence_threshold == 0.7
    assert t.latency_threshold_ms == 500.0
    assert t.calibration_error_threshold == 0.05
    assert t.fallback_rate_threshold == 0.2
