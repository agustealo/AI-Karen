from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask


@pytest.mark.asyncio
async def test_public_classify_returns_registered_predictor_truth() -> None:
    async def fake_predict(
        features: IntelligenceFeatures,
        task: PredictionTask,
    ) -> Prediction:
        assert features.text == "Fix this error"
        assert task == PredictionTask.INTENT
        return Prediction(
            task=PredictionTask.INTENT,
            label="problem_solving",
            probability=0.82,
            confidence=0.78,
            model_id="intent-model",
            model_version="v2",
            feature_version="v1",
            fallback_used=False,
            inference_method="embedding_similarity",
            metadata={"burn": True},
        )

    runtime = object.__new__(IntelligenceRuntime)
    runtime._initialized = True
    runtime._ml_runtime = SimpleNamespace(predict=fake_predict)

    result = await runtime.classify("intent", "Fix this error")

    assert result == {
        "task": "intent",
        "label": "problem_solving",
        "confidence": 0.78,
        "probability": 0.82,
        "source_type": "transformer",
        "model_id": "intent-model",
        "model_version": "v2",
        "feature_version": "v1",
        "fallback_used": False,
        "inference_method": "embedding_similarity",
        "latency_ms": 0.0,
        "metadata": {"burn": True},
    }


@pytest.mark.asyncio
async def test_public_classify_rejects_unknown_prediction_task_without_fake_model_truth() -> None:
    runtime = object.__new__(IntelligenceRuntime)
    runtime._initialized = True
    runtime._ml_runtime = SimpleNamespace()

    result = await runtime.classify("not-a-real-task", "hello")

    assert result["label"] == "unknown"
    assert result["confidence"] == 0.0
    assert result["fallback_used"] is True
    assert result["source_type"] == "fallback"
    assert result["inference_method"] == "unsupported_task"
