from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.ml_runtime import MLRuntime
from ai_karen_engine.core.intelligence.ml.predictors.intent import IntentPredictor
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures


@pytest.mark.asyncio
async def test_ml_runtime_initialize():
    runtime = MLRuntime()
    await runtime.initialize()
    health = await runtime.health()
    assert "overall" in health


@pytest.mark.asyncio
async def test_ml_runtime_encode():
    runtime = MLRuntime()
    await runtime.initialize()
    encoding = await runtime.encode("Hello world", "default")
    assert encoding is None or hasattr(encoding, "vector")


@pytest.mark.asyncio
async def test_ml_runtime_predict():
    runtime = MLRuntime()
    await runtime.initialize()
    runtime.register_predictor("intent", IntentPredictor(runtime))
    features = IntelligenceFeatures(text="Hello")
    result = await runtime.predict(features, "intent")
    assert result is None or result.task.value == "intent"
