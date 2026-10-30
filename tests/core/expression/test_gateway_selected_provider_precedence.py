"""Explicit provider/model choice cannot be replaced by engine defaults."""
from unittest.mock import patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionResult, ExpressionTask
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings


@pytest.mark.asyncio
async def test_requested_provider_and_model_survive_primary_engine_defaults():
    settings = ExpressionSettings(active_engine="local", engine_fallback_order=[])
    settings.engines["local"] = EngineConfig(
        enabled=True,
        type="builtin_provider_engine",
        metadata={"preferred_provider": "ollama-local", "preferred_model": "default-4b"},
    )
    seen = []

    class Engine:
        async def generate(self, task):
            seen.append((task.preferred_provider, task.preferred_model))
            return ExpressionResult(
                task_id=task.task_id,
                text="Valid model response.",
                provider=task.preferred_provider,
                model=task.preferred_model,
                engine_id="local",
                engine_mode="local",
                runtime_engine="local",
                response_source="model",
                attempts=[],
                skipped=[],
                latency_ms=1.0,
                degraded=False,
            )

    task = ExpressionTask(
        task_id="selection-proof",
        kind="chat",
        messages=[{"role": "user", "content": "Hello"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider="ollama",
        preferred_model="deepseek-r1:1.5b",
    )
    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        result = await ExpressionGateway(settings).generate(task)

    assert seen == [("ollama", "deepseek-r1:1.5b")]
    assert result.provider == "ollama"
    assert result.model == "deepseek-r1:1.5b"
    assert task.preferred_provider == "ollama"
    assert task.preferred_model == "deepseek-r1:1.5b"


def test_local_engine_resolves_saved_ollama_before_other_healthy_endpoints(monkeypatch):
    """Regression: 'chat' capability must satisfy OpenAI-compatible chat."""
    from types import SimpleNamespace

    from ai_karen_engine.core.expression.engines.openai_compatible_engine import (
        OpenAICompatibleEngine,
    )
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )

    registry = ProviderRegistryService()
    # This test exercises routing, not network/service readiness. Both the
    # selected target and competing local providers are considered healthy.
    monkeypatch.setattr(
        registry, "get_provider_status",
        lambda provider_id: SimpleNamespace(is_available=True),
    )
    task = ExpressionTask(
        task_id="real-ollama-preference-contract",
        kind="chat",
        messages=[{"role": "user", "content": "Describe an original landscape."}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider="ollama-local",
        preferred_model="smollm2:135m",
    )
    assert OpenAICompatibleEngine()._resolve_provider(
        task, False, registry,
    ) == "ollama-local"
    assert task.preferred_model == "smollm2:135m"
