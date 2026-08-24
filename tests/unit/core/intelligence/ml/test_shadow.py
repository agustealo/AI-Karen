from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus, Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.shadow import ShadowEvaluator, ShadowEvaluation


class FakePredictor:
    def __init__(self, label: str, confidence: float, fallback: bool = False, latency_ms: float = 1.0) -> None:
        self._label = label
        self._confidence = confidence
        self._fallback = fallback
        self._latency_ms = latency_ms

    async def predict(self, features: IntelligenceFeatures):
        return Prediction(
            task=PredictionTask.INTENT,
            label=self._label,
            confidence=self._confidence,
            fallback_used=self._fallback,
            latency_ms=self._latency_ms,
        )


def _setup_registry(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    active = MLModelManifest(
        model_id="active-model", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    shadow = MLModelManifest(
        model_id="shadow-model", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v2", feature_version="v1", status=ModelStatus.SHADOW.value,
    )
    registry.register(active)
    registry.register(shadow)
    return registry


@pytest.mark.asyncio
async def test_shadow_evaluate_returns_none_without_models(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    evaluator = ShadowEvaluator(registry=registry)
    features = IntelligenceFeatures(text="hello")
    result = await evaluator.evaluate_shadow("intent", features, FakePredictor("a", 0.9), FakePredictor("a", 0.9))
    assert result is None


@pytest.mark.asyncio
async def test_shadow_evaluate_success(tmp_path):
    registry = _setup_registry(tmp_path)
    evaluator = ShadowEvaluator(registry=registry)
    active = FakePredictor("information_seeking", 0.9)
    shadow = FakePredictor("information_seeking", 0.8)
    features = IntelligenceFeatures(text="What is AI?")
    result = await evaluator.evaluate_shadow("intent", features, active, shadow)
    assert result is not None
    assert result.agreement is True
    assert result.label_match is True
    assert result.active_model_id == "active-model"
    assert result.shadow_model_id == "shadow-model"
    assert result.confidence_delta == pytest.approx(-0.1)


@pytest.mark.asyncio
async def test_shadow_evaluate_disagreement(tmp_path):
    registry = _setup_registry(tmp_path)
    evaluator = ShadowEvaluator(registry=registry)
    active = FakePredictor("information_seeking", 0.9)
    shadow = FakePredictor("task_completion", 0.8)
    features = IntelligenceFeatures(text="hello")
    result = await evaluator.evaluate_shadow("intent", features, active, shadow)
    assert result is not None
    assert result.agreement is False
    assert result.label_match is False
    assert result.confidence_delta == pytest.approx(-0.1)


@pytest.mark.asyncio
async def test_shadow_compare_returns_none_without_models(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    evaluator = ShadowEvaluator(registry=registry)
    evaluations = []
    result = await evaluator.compare_shadow("intent", evaluations)
    assert result is None


@pytest.mark.asyncio
async def test_shadow_compare_success(tmp_path):
    registry = _setup_registry(tmp_path)
    evaluator = ShadowEvaluator(registry=registry)
    evaluations = [
        ShadowEvaluation(
            evaluation_id="e1", purpose="intent",
            active_model_id="active-model", active_model_version="v1",
            shadow_model_id="shadow-model", shadow_model_version="v2",
            feature_version="v1", input_text="hello",
            agreement=True, label_match=True, confidence_delta=0.1,
            latency_delta_ms=5.0, active_fallback=False, shadow_fallback=False,
        ),
        ShadowEvaluation(
            evaluation_id="e2", purpose="intent",
            active_model_id="active-model", active_model_version="v1",
            shadow_model_id="shadow-model", shadow_model_version="v2",
            feature_version="v1", input_text="world",
            agreement=False, label_match=False, confidence_delta=-0.2,
            latency_delta_ms=-3.0, active_fallback=True, shadow_fallback=False,
        ),
    ]
    result = await evaluator.compare_shadow("intent", evaluations)
    assert result is not None
    assert result.sample_count == 2
    assert result.agreement_rate == 0.5
    assert result.label_disagreement_count == 1
    assert result.avg_confidence_delta == pytest.approx(0.15)
    assert result.avg_latency_delta_ms == pytest.approx(1.0)
    assert result.regression_count == 0
    assert result.active_fallback_rate == 0.5
    assert result.shadow_fallback_rate == 0.0


@pytest.mark.asyncio
async def test_shadow_compare_regression(tmp_path):
    registry = _setup_registry(tmp_path)
    evaluator = ShadowEvaluator(registry=registry)
    evaluations = [
        ShadowEvaluation(
            evaluation_id="e1", purpose="intent",
            active_model_id="active-model", active_model_version="v1",
            shadow_model_id="shadow-model", shadow_model_version="v2",
            feature_version="v1", input_text="hello",
            active_correct=True, shadow_correct=False,
            agreement=False, label_match=False,
        ),
    ]
    result = await evaluator.compare_shadow("intent", evaluations)
    assert result is not None
    assert result.regression_count == 1


@pytest.mark.asyncio
async def test_shadow_evaluate_predictor_exception(tmp_path):
    registry = _setup_registry(tmp_path)
    evaluator = ShadowEvaluator(registry=registry)

    class BoomPredictor:
        async def predict(self, features):
            raise RuntimeError("boom")

    features = IntelligenceFeatures(text="hello")
    result = await evaluator.evaluate_shadow("intent", features, FakePredictor("a", 0.9), BoomPredictor())
    assert result is not None
    assert result.shadow_prediction is None
