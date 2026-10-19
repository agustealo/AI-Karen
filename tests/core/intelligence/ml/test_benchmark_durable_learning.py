"""Canonical evaluated predictors, not self-reports, feed durable ML learning."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkResult, PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner


def benchmark(*, missing=False, fallback=False, wrong_model=False):
    prediction = (
        None if missing else Prediction(
            task=PredictionTask.INTENT,
            label="private-predicted-label",
            model_id="different-model" if wrong_model else "candidate-verified",
            model_version="v1",
            feature_version="features-v2",
            probability=0.9,
            confidence=0.9,
            fallback_used=fallback,
        )
    )
    record = PredictionOutcome(
        case_id="private-benchmark-case-id",
        task=PredictionTask.INTENT,
        prediction=prediction,
        expected_label="private-expected-label",
        correct=(not missing and not wrong_model),
        raw_probability=0.9,
        calibrated_probability=0.9,
        latency_ms=18.0,
        fallback_used=fallback,
    )
    return BenchmarkResult(
        model_id="candidate-verified", model_version="v1",
        task=PredictionTask.INTENT,
        dataset_version="dataset-v2",
        sample_count=1, metrics={}, latency_p50_ms=18,
        latency_p95_ms=18, error_count=0, fallback_count=int(fallback),
        abstention_count=0, outcomes=[record],
    )


@pytest.mark.asyncio
async def test_evaluated_benchmark_projects_only_numeric_redacted_evidence(monkeypatch):
    from ai_karen_engine.core.intelligence.ml import durable_outcomes

    saved = []

    class CapturingProjection:
        def __init__(self, *, tenant_id, user_id):
            assert tenant_id == "tenant-1"
            assert user_id == "user-1"

        async def record_verified_batch(self, observations):
            saved.extend(observations)
            return {"stored": True, "stored_count": len(observations)}

    monkeypatch.setattr(
        durable_outcomes, "GovernedMLLearningEvidence", CapturingProjection,
    )
    count = await BenchmarkRunner._project_verified_ml_evidence(
        result=benchmark(), receipt="benchmark-receipt-1",
        tenant_id="tenant-1", user_id="user-1",
    )
    assert count == 1
    record, label_source, reference = saved[0]
    assert record.correct is True
    assert record.calibration_error == pytest.approx(0.1)
    assert record.feature_version == "features-v2"
    assert record.predicted_label == ""
    assert record.expected_label == ""
    assert record.model_id == "candidate-verified"
    assert label_source == "heldout_evaluation"
    assert reference.startswith("benchmark:benchmark-receipt-1:")
    assert "private-benchmark-case-id" not in reference


@pytest.mark.asyncio
async def test_fallback_and_missing_predictor_are_excluded_from_learning(monkeypatch):
    from ai_karen_engine.core.intelligence.ml import durable_outcomes

    called = []
    class EmptyProjection:
        def __init__(self, *, tenant_id, user_id):
            pass

        async def record_verified_batch(self, *args, **kwargs):
            called.append(True)
            return {"stored": True, "stored_count": 0}

    monkeypatch.setattr(
        durable_outcomes, "GovernedMLLearningEvidence", EmptyProjection,
    )
    for result in [benchmark(missing=True), benchmark(fallback=True)]:
        count = await BenchmarkRunner._project_verified_ml_evidence(
            result=result, receipt="benchmark-receipt-1",
            tenant_id="tenant-1", user_id="user-1",
        )
        assert count == 0
    assert called == []


@pytest.mark.asyncio
async def test_wrong_model_or_incomplete_corpus_cannot_contaminate_evidence():
    with pytest.raises(ValueError, match="identity mismatch"):
        await BenchmarkRunner._project_verified_ml_evidence(
            result=benchmark(wrong_model=True), receipt="receipt-1",
            tenant_id="tenant-1", user_id="user-1",
        )
    incomplete = benchmark()
    incomplete.sample_count = 2
    with pytest.raises(ValueError, match="incomplete"):
        await BenchmarkRunner._project_verified_ml_evidence(
            result=incomplete, receipt="receipt-1",
            tenant_id="tenant-1", user_id="user-1",
        )


@pytest.mark.asyncio
async def test_persistence_failure_is_never_a_false_learning_success(monkeypatch):
    from ai_karen_engine.core.intelligence.ml import durable_outcomes

    class FailingProjection:
        def __init__(self, *, tenant_id, user_id):
            pass

        async def record_verified_batch(self, *args, **kwargs):
            raise RuntimeError("PostgreSQL rejected the durable evidence")

    monkeypatch.setattr(
        durable_outcomes, "GovernedMLLearningEvidence", FailingProjection,
    )
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        await BenchmarkRunner._project_verified_ml_evidence(
            result=benchmark(), receipt="benchmark-receipt-1",
            tenant_id="tenant-1", user_id="user-1",
        )


def test_evaluated_predictor_persistence_is_explicit_and_default_off(monkeypatch):
    from ai_karen_engine.config.learning import LearningSettings
    assert LearningSettings().verified_evaluation_outcomes_enabled is False
    monkeypatch.setenv("LEARNING_VERIFIED_EVALUATION_OUTCOMES_ENABLED", "garbage")
    with pytest.raises(ValueError, match="must be boolean"):
        LearningSettings().apply_env_overrides()
