from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import (
    BenchmarkConfig,
    EvaluationCase,
    PredictionOutcome,
)
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import CanonicalEvaluationCorpus
from ai_karen_engine.core.intelligence.ml.evaluation.metrics import (
    compute_brier_score,
    compute_capability_metrics,
    compute_classification_metrics,
    compute_ece,
    compute_latency_metrics,
    compute_reliability_curve,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner


@pytest.mark.asyncio
async def test_corpus_contains_all_tasks():
    cases = CanonicalEvaluationCorpus.all_cases()
    tasks = {c.task for c in cases}
    assert PredictionTask.INTENT in tasks
    assert PredictionTask.DOMAIN in tasks
    assert PredictionTask.COMPLEXITY in tasks
    assert PredictionTask.AMBIGUITY in tasks
    assert PredictionTask.MEMORY_RELEVANCE in tasks
    assert PredictionTask.CAPABILITY in tasks


@pytest.mark.asyncio
async def test_corpus_filtering():
    cases = CanonicalEvaluationCorpus.get_cases(
        task=PredictionTask.INTENT, tags=["adversarial"]
    )
    assert all(c.task == PredictionTask.INTENT for c in cases)
    assert all("adversarial" in c.tags for c in cases)


@pytest.mark.asyncio
async def test_corpus_case_count():
    cases = CanonicalEvaluationCorpus.get_cases(task=PredictionTask.INTENT)
    assert len(cases) >= 10


@pytest.mark.asyncio
async def test_classification_metrics_all_correct():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, label="a"),
            expected_label="a",
            correct=True,
            raw_probability=0.9,
            calibrated_probability=0.9,
        ),
        PredictionOutcome(
            case_id="c2",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, label="b"),
            expected_label="b",
            correct=True,
            raw_probability=0.8,
            calibrated_probability=0.8,
        ),
    ]
    metrics = compute_classification_metrics(outcomes)
    assert metrics["accuracy"].value == 1.0
    assert metrics["macro_f1"].value == 1.0


@pytest.mark.asyncio
async def test_classification_metrics_all_wrong():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, label="a"),
            expected_label="b",
            correct=False,
            raw_probability=0.9,
            calibrated_probability=0.9,
        ),
    ]
    metrics = compute_classification_metrics(outcomes)
    assert metrics["accuracy"].value == 0.0
    assert metrics["macro_f1"].value == 0.0


@pytest.mark.asyncio
async def test_capability_metrics():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.CAPABILITY,
            prediction=Prediction(
                task=PredictionTask.CAPABILITY,
                label="candidates",
                value={"web_search": 0.8, "code_execution": 0.1},
            ),
            expected_label="web_search",
            expected_value=["web_search"],
            correct=True,
            raw_probability=0.8,
            calibrated_probability=0.8,
        ),
        PredictionOutcome(
            case_id="c2",
            task=PredictionTask.CAPABILITY,
            prediction=Prediction(
                task=PredictionTask.CAPABILITY,
                label="candidates",
                value={"web_search": 0.9, "calendar": 0.7},
            ),
            expected_label="web_search,calendar",
            expected_value=["web_search", "calendar"],
            correct=True,
            raw_probability=0.9,
            calibrated_probability=0.9,
        ),
    ]
    metrics = compute_capability_metrics(outcomes)
    assert "micro_f1" in metrics
    assert "macro_f1" in metrics


@pytest.mark.asyncio
async def test_brier_score_perfect():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=1.0, confidence=1.0),
            expected_label="a",
            correct=True,
            raw_probability=1.0,
            calibrated_probability=1.0,
        ),
    ]
    assert compute_brier_score(outcomes).value == 0.0


@pytest.mark.asyncio
async def test_brier_score_worst():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=1.0, confidence=1.0),
            expected_label="a",
            correct=False,
            raw_probability=1.0,
            calibrated_probability=1.0,
        ),
    ]
    assert compute_brier_score(outcomes).value == 1.0


@pytest.mark.asyncio
async def test_ece_perfect():
    outcomes = [
        PredictionOutcome(
            case_id=f"c{i}",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=1.0, confidence=1.0),
            expected_label="a",
            correct=True,
            raw_probability=1.0,
            calibrated_probability=1.0,
        )
        for i in range(10)
    ]
    metric, bins = compute_ece(outcomes, n_bins=10)
    assert metric.value == pytest.approx(0.0, abs=1e-6)
    assert len(bins) == 1


@pytest.mark.asyncio
async def test_ece_miscalibrated():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=0.9, confidence=0.9),
            expected_label="a",
            correct=False,
            raw_probability=0.9,
            calibrated_probability=0.9,
        ),
        PredictionOutcome(
            case_id="c2",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=0.1, confidence=0.1),
            expected_label="a",
            correct=True,
            raw_probability=0.1,
            calibrated_probability=0.1,
        ),
    ]
    metric, bins = compute_ece(outcomes, n_bins=10)
    assert metric.value > 0.0


@pytest.mark.asyncio
async def test_reliability_curve():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT, probability=0.9, confidence=0.9),
            expected_label="a",
            correct=True,
            raw_probability=0.9,
            calibrated_probability=0.9,
        ),
    ]
    bins = compute_reliability_curve(outcomes, n_bins=10)
    assert len(bins) == 1
    assert bins[0].count == 1


@pytest.mark.asyncio
async def test_latency_metrics():
    outcomes = [
        PredictionOutcome(
            case_id="c1",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT),
            expected_label="a",
            correct=True,
            latency_ms=10.0,
        ),
        PredictionOutcome(
            case_id="c2",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT),
            expected_label="a",
            correct=True,
            latency_ms=20.0,
        ),
        PredictionOutcome(
            case_id="c3",
            task=PredictionTask.INTENT,
            prediction=Prediction(task=PredictionTask.INTENT),
            expected_label="a",
            correct=True,
            latency_ms=30.0,
        ),
    ]
    metrics = compute_latency_metrics(outcomes)
    assert metrics["p50_latency_ms"].value == 20.0
    assert metrics["p95_latency_ms"].value == 29.0


@pytest.mark.asyncio
async def test_runner_with_mock_predictor():
    class MockPredictor:
        async def predict(self, features):
            return Prediction(task=PredictionTask.INTENT, label="information_seeking", confidence=0.9)

    runner = BenchmarkRunner()
    config = BenchmarkConfig(
        model_id="mock-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001"],
    )
    result = await runner.run(MockPredictor(), config)
    assert result.sample_count == 1
    assert result.model_id == "mock-model"
    assert "accuracy" in result.metrics


@pytest.mark.asyncio
async def test_runner_error_handling():
    class FailingPredictor:
        async def predict(self, features):
            raise RuntimeError("predictor boom")

    runner = BenchmarkRunner()
    config = BenchmarkConfig(
        model_id="failing-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001"],
    )
    result = await runner.run(FailingPredictor(), config)
    assert result.error_count == 1
    assert result.sample_count == 1


@pytest.mark.asyncio
async def test_runner_sync_predictor():
    class SyncPredictor:
        def predict(self, features):
            return Prediction(task=PredictionTask.INTENT, label="information_seeking", confidence=0.9)

    runner = BenchmarkRunner()
    config = BenchmarkConfig(
        model_id="sync-model",
        model_version="v1",
        task=PredictionTask.INTENT,
        case_ids=["intent-001"],
    )
    result = await runner.run(SyncPredictor(), config)
    assert result.sample_count == 1
    assert result.metrics["accuracy"].value == 1.0
