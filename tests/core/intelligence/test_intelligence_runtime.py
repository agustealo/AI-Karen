from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime


@pytest.mark.asyncio
async def test_intelligence_runtime_analyze():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    result = await runtime.analyze("What is the weather today?")
    assert result is not None
    assert hasattr(result, "intent")
    assert hasattr(result, "signals")
    assert hasattr(result, "latency_ms")


@pytest.mark.asyncio
async def test_intelligence_runtime_empty_text():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    result = await runtime.analyze("")
    assert result.degraded is True


@pytest.mark.asyncio
async def test_intelligence_runtime_health():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    health = await runtime.health()
    assert "overall" in health


@pytest.mark.asyncio
async def test_intelligence_runtime_embed():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    embeddings = await runtime.embed(["Hello world"])
    assert isinstance(embeddings, list)


@pytest.mark.asyncio
async def test_intelligence_runtime_classify():
    runtime = IntelligenceRuntime()
    await runtime.initialize()
    result = await runtime.classify("general", "Hello world")
    assert "task" in result
    assert "label" in result


@pytest.mark.asyncio
async def test_classify_forwards_explicit_tenant_scope_without_global_mutation():
    from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask

    class CapturingML:
        def __init__(self):
            self.scopes = []

        async def predict(self, features, task):
            self.scopes.append((features.tenant_id, task))
            return None

    runtime = IntelligenceRuntime()
    runtime.initialize = _no_op_async
    capture = CapturingML()
    runtime._ml_runtime = capture
    for tenant in ("tenant-a", "tenant-b", None):
        await runtime.classify("affect", "test", tenant_id=tenant)
    assert capture.scopes == [
        ("tenant-a", PredictionTask.AFFECT),
        ("tenant-b", PredictionTask.AFFECT),
        (None, PredictionTask.AFFECT),
    ]


async def _no_op_async():
    return None
