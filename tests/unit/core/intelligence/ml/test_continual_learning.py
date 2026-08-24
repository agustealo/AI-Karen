from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.continual_learning import ContinualRetrainingPipeline, RetrainingTrigger
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.online_learning import AdaptiveLayer, MLOutcomeRecord
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry


def _make_outcome(model_id: str, correct: bool, task: PredictionTask = PredictionTask.INTENT, latency: float = 10.0, calibration_error: float = 0.02, fallback: bool = False):
    return MLOutcomeRecord(
        outcome_id=f"o-{model_id}",
        task=task,
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


def test_evaluate_triggers_low_accuracy(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = ContinualRetrainingPipeline(registry=registry)
    for i in range(60):
        pipeline._adaptive_layer.record_outcome(_make_outcome("m1", correct=(i % 10 == 0)))
    triggers = pipeline.evaluate_triggers(min_samples=50)
    assert len(triggers) == 1
    assert triggers[0].reason == "low_accuracy"
    assert triggers[0].model_id == "m1"


def test_evaluate_triggers_poor_calibration(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = ContinualRetrainingPipeline(registry=registry)
    for i in range(100):
        outcome = _make_outcome("m1", correct=True, calibration_error=0.15)
        pipeline._adaptive_layer.record_outcome(outcome)
    triggers = pipeline.evaluate_triggers(min_samples=50)
    reasons = [t.reason for t in triggers]
    assert "poor_calibration" in reasons


def test_evaluate_triggers_high_fallback(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = ContinualRetrainingPipeline(registry=registry)
    for i in range(60):
        outcome = _make_outcome("m1", correct=True)
        outcome.fallback_used = True
        pipeline._adaptive_layer.record_outcome(outcome)
    triggers = pipeline.evaluate_triggers(min_samples=50)
    assert len(triggers) == 1
    assert triggers[0].reason == "high_fallback_rate"


def test_evaluate_triggers_insufficient_samples(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = ContinualRetrainingPipeline(registry=registry)
    for i in range(10):
        pipeline._adaptive_layer.record_outcome(_make_outcome("m1", correct=True))
    triggers = pipeline.evaluate_triggers(min_samples=50)
    assert len(triggers) == 0


def test_submit_retraining_job(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    pipeline = ContinualRetrainingPipeline(registry=registry)
    trigger = RetrainingTrigger(
        model_id="m1",
        model_version="v1",
        task=PredictionTask.INTENT,
        reason="low_accuracy",
        evidence_profile=pipeline._adaptive_layer.get_profile("m1", "v1", PredictionTask.INTENT) or pipeline._adaptive_layer._aggregator._profiles.__class__(),
    )
    # Need a real evidence profile
    for i in range(60):
        pipeline._adaptive_layer.record_outcome(_make_outcome("m1", correct=False))
    profile = pipeline._adaptive_layer.get_profile("m1", "v1", PredictionTask.INTENT)
    trigger = RetrainingTrigger(
        model_id="m1",
        model_version="v1",
        task=PredictionTask.INTENT,
        reason="low_accuracy",
        evidence_profile=profile,
    )
    result = pipeline.submit_retraining_job(trigger)
    assert result.job.status == "QUEUED"
    assert result.job.metadata.get("trigger_reason") == "low_accuracy"
