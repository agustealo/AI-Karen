"""Completion evidence must survive the canonical OpenAI-compatible engine."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.expression.engines.openai_compatible_engine import (
    OpenAICompatibleEngine,
)
from ai_karen_engine.core.model_runtime import provider_registry_service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "expected_truncated"),
    [("length", True), ("stop", False), (None, False)],
)
async def test_canonical_engine_carries_provider_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
    expected_truncated: bool,
) -> None:
    from ai_karen_engine.core.expression.engines import openai_compatible_engine as module

    endpoint = SimpleNamespace(provider_id="ollama-local")
    registry = SimpleNamespace(get_provider_endpoint=lambda _name: endpoint)
    monkeypatch.setattr(
        provider_registry_service,
        "get_provider_registry_service",
        lambda: registry,
    )
    # Engine imports the registry accessor locally; patch the canonical module.
    monkeypatch.setattr(
        OpenAICompatibleEngine,
        "_resolve_provider",
        lambda self, task, is_cloud, registry: "ollama-local",
    )

    async def execute(*args, **kwargs):
        return SimpleNamespace(
            text="Generated output",
            provider_id="ollama-local",
            model="qwen3:4b",
            runtime_engine="ollama",
            usage={"completion_tokens": 24},
            finish_reason=finish_reason,
        )

    monkeypatch.setattr(module, "execute_provider_endpoint", execute)
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    task = ExpressionTask(
        task_id="finish-reason",
        kind="chat",
        messages=[{"role": "user", "content": "Explain"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider="auto",
        preferred_model="qwen3:4b",
        max_tokens=24,
        temperature=0.2,
    )
    result = await engine.generate(task)
    assert result.text == "Generated output"
    assert result.metadata["finish_reason"] == finish_reason
    assert result.metadata["output_truncated"] is expected_truncated
