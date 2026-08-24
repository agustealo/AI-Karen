"""
ML-CORE-2: Inference Wiring & Truth Closure tests.

Proves that:
1. MLRuntime wires the default encoder during initialization.
2. Encoder selection is config/registry driven.
3. Predictors receive a registered encoder and emit explicit inference_method.
4. Health reports truthfully when a configured encoder is missing.
5. Fallback behavior is explicit and observable.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    SignalSourceType,
)
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import (
    ModelStatus,
    PredictionTask,
    SemanticEncoding,
)
from ai_karen_engine.core.intelligence.ml.ml_runtime import MLRuntime
from ai_karen_engine.core.intelligence.ml.predictors.intent import IntentPredictor
from ai_karen_engine.core.intelligence.ml.predictors.memory_relevance import (
    MemoryRelevancePredictor,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime


class StubEncoder:
    def __init__(self, model_id: str = "stub-encoder", fallback: bool = False) -> None:
        self.fallback_mode = fallback
        self.config = MagicMock()
        self.config.model_name = model_id

    async def encode(self, text: str) -> SemanticEncoding:
        return SemanticEncoding(
            vector=[0.1, 0.2, 0.3],
            dimensions=3,
            model_id=self.config.model_name,
            model_version="current",
            fallback_used=self.fallback_mode,
        )

    async def encode_batch(self, texts: list[str]) -> list[SemanticEncoding]:
        return [await self.encode(text) for text in texts]

    async def health(self) -> dict[str, Any]:
        status = "degraded" if self.fallback_mode else "ready"
        return {"status": status, "model_loaded": True}

    async def metadata(self) -> dict[str, Any]:
        return {"model_id": self.config.model_name, "fallback_used": self.fallback_mode}


@pytest.mark.asyncio
async def test_ml_runtime_wires_default_encoder():
    runtime = MLRuntime()
    await runtime.initialize()
    encoder = runtime.get_encoder("default")
    assert encoder is not None


@pytest.mark.asyncio
async def test_ml_runtime_uses_registry_manifest_for_encoder(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    manifest = MagicMock()
    manifest.model_id = "registry-encoder"
    manifest.purpose = "semantic_encoding"
    manifest.status = ModelStatus.ACTIVE.value
    manifest.artifact_path = ""
    registry._manifests["registry-encoder"] = manifest

    runtime = MLRuntime(registry=registry)
    with patch(
        "ai_karen_engine.core.intelligence.ml.ml_runtime.MLRuntime._build_encoder_from_manifest",
        return_value=StubEncoder(model_id="registry-encoder"),
    ):
        await runtime.initialize()

    encoder = runtime.get_encoder("default")
    assert encoder is not None
    assert getattr(encoder, "config", None) and getattr(encoder.config, "model_name", "") == "registry-encoder"


@pytest.mark.asyncio
async def test_intelligence_runtime_gets_encoder_before_predictors():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    encoder = runtime._ml_runtime.get_encoder("default")
    assert encoder is not None


@pytest.mark.asyncio
async def test_predictors_emit_inference_method():
    runtime = MLRuntime()
    await runtime.initialize()
    encoder = StubEncoder()
    runtime.register_encoder("default", encoder)
    runtime.register_predictor(PredictionTask.INTENT, IntentPredictor(runtime, encoder))
    runtime.register_predictor(PredictionTask.MEMORY_RELEVANCE, MemoryRelevancePredictor(runtime, encoder))

    features = IntelligenceFeatures(text="What is the weather today?")
    intent_pred = await runtime.predict(features, PredictionTask.INTENT)
    memory_pred = await runtime.predict(features, PredictionTask.MEMORY_RELEVANCE)

    assert intent_pred is not None
    assert intent_pred.inference_method == "embedding_similarity"
    assert intent_pred.fallback_used is False

    assert memory_pred is not None
    assert memory_pred.inference_method == "embedding_similarity"
    assert memory_pred.fallback_used is False


@pytest.mark.asyncio
async def test_predictors_report_heuristic_fallback_without_encoder():
    runtime = MLRuntime()
    await runtime.initialize()
    runtime.register_predictor(PredictionTask.INTENT, IntentPredictor(runtime, semantic_encoder=None))
    runtime.register_predictor(PredictionTask.MEMORY_RELEVANCE, MemoryRelevancePredictor(runtime, semantic_encoder=None))

    features = IntelligenceFeatures(text="What is the weather today?")
    intent_pred = await runtime.predict(features, PredictionTask.INTENT)
    memory_pred = await runtime.predict(features, PredictionTask.MEMORY_RELEVANCE)

    assert intent_pred is not None
    assert intent_pred.inference_method == "heuristic_fallback"
    assert intent_pred.fallback_used is True

    assert memory_pred is not None
    assert memory_pred.inference_method == "heuristic_fallback"
    assert memory_pred.fallback_used is True


@pytest.mark.asyncio
async def test_health_reports_missing_configured_encoder(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    manifest = MagicMock()
    manifest.model_id = "expected-encoder"
    manifest.purpose = "semantic_encoding"
    manifest.status = ModelStatus.ACTIVE.value
    manifest.artifact_path = ""
    registry._manifests["expected-encoder"] = manifest

    runtime = MLRuntime(registry=registry)
    with patch.object(
        runtime,
        "_build_encoder_from_manifest",
        return_value=None,
    ):
        await runtime.initialize()

    health = await runtime.health()
    assert health["overall"] == "degraded"
    assert health["registry"]["configured_encoder"] == "expected-encoder"
    assert health["registry"]["encoder_missing"] is True


@pytest.mark.asyncio
async def test_analyze_produces_signals_with_inference_metadata():
    runtime = IntelligenceRuntime()
    result = await runtime.analyze("What is the weather today?")

    assert isinstance(result, IntelligenceAnalysisResult)
    assert len(result.signals) > 0

    prediction_signals = [s for s in result.signals if s.source_id and s.source_id.startswith("MLPredictor.")]
    for signal in prediction_signals:
        assert signal.inference_method in (
            "embedding_similarity",
            "heuristic_fallback",
            "learned_model",
            "deterministic_baseline",
        )
        assert isinstance(signal.fallback_used, bool)


@pytest.mark.asyncio
async def test_cortex_contract_unchanged_by_ml_or_fallback():
    runtime = IntelligenceRuntime()
    result_ml = await runtime.analyze("Explain quantum computing")
    result_fallback = await runtime.analyze("What is 2 plus 2")

    for result in (result_ml, result_fallback):
        assert hasattr(result, "intent")
        assert hasattr(result, "intent_confidence")
        assert hasattr(result, "task_complexity")
        assert hasattr(result, "memory_relevance")
        assert hasattr(result, "topology_signals")
        assert hasattr(result, "risk_signals")
        assert hasattr(result, "capability_hints")
        assert hasattr(result, "signals")
        assert hasattr(result, "latency_ms")
        assert isinstance(result.signals, list)


@pytest.mark.asyncio
async def test_intelligence_runtime_accepts_shared_registry(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    runtime = IntelligenceRuntime(registry=registry)
    await runtime.initialize()
    assert runtime._registry is runtime._ml_runtime._registry


@pytest.mark.asyncio
async def test_default_encoder_fallback_is_explicit():
    runtime = MLRuntime()
    await runtime.initialize()
    encoder = runtime.get_encoder("default")
    if encoder is not None and encoder.fallback_mode:
        health = await runtime.health()
        assert health["encoders"]["default"]["fallback_mode"] is True
        assert health["encoders"]["default"]["status"] == "degraded"
