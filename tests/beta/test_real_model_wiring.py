from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.expression.engines.builtin_provider_engine import (
    BuiltinProviderEngine,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS
from ai_karen_engine.core.model_runtime.provider_execution import (
    get_provider_execution_registry,
    register_provider_factory,
)


REQUIRED_GENERATIVE_CAPABILITIES = {"chat_completion", "text_generation"}


def _task() -> ExpressionTask:
    return ExpressionTask(
        task_id="beta-proof",
        kind="chat",
        messages=[{"role": "user", "content": "Return BETA_REAL_MODEL_OK"}],
        response_mode="text",
        required_capabilities=["chat_completion"],
        forbidden_capabilities=[],
        preferred_provider="builtin_vllm",
        preferred_model="beta-model",
        max_tokens=32,
        temperature=0.0,
        timeout_ms=5000,
        correlation_id="beta-correlation",
        request_id="beta-request",
    )


@pytest.fixture(autouse=True)
def _reset_provider_execution_registry():
    registry = get_provider_execution_registry()
    registry.clear_factory()
    yield
    registry.clear_factory()


def test_local_generative_endpoints_use_canonical_capabilities() -> None:
    endpoints = {endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS}

    for provider_id in ("lmstudio-desktop", "ollama-local", "llamacpp-server"):
        endpoint = endpoints[provider_id]
        assert REQUIRED_GENERATIVE_CAPABILITIES.issubset(
            {capability.lower() for capability in endpoint.capabilities}
        )
        assert endpoint.base_url
        assert endpoint.fallback_eligible is True


@pytest.mark.asyncio
async def test_builtin_provider_executes_registered_provider_and_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.expression.engines import builtin_provider_engine as module

    endpoint = SimpleNamespace(provider_id="builtin_vllm")

    class FakeRegistry:
        def select_best_target(self, **kwargs):
            assert kwargs["required_capabilities"] == REQUIRED_GENERATIVE_CAPABILITIES
            assert kwargs["healthy_only"] is True
            return endpoint

        def resolve_capable_targets(self, *args, **kwargs):
            return [endpoint]

    class FakeProvider:
        model = "beta-model"

        async def generate_text_async(self, prompt: str, **payload):
            assert prompt == "Return BETA_REAL_MODEL_OK"
            assert payload["messages"] == _task().messages
            return "BETA_REAL_MODEL_OK"

    monkeypatch.setattr(module, "get_provider_registry_service", lambda: FakeRegistry())
    monkeypatch.setattr(
        module,
        "evaluate_provider_policy",
        lambda provider_id: SimpleNamespace(classification="builtin_engine"),
    )

    register_provider_factory(lambda provider_id, **kwargs: FakeProvider())

    result = await BuiltinProviderEngine().generate(_task())

    assert result.text == "BETA_REAL_MODEL_OK"
    assert result.provider == "builtin_vllm"
    assert result.model == "beta-model"
    assert result.runtime_engine == "vllm"
    assert result.response_source == "provider_runtime"
    assert result.degraded is False
    assert result.metadata["actual_provider"] == "builtin_vllm"
    assert result.metadata["actual_model"] == "beta-model"
    assert result.metadata["fallback_level"] == 0
    assert result.attempts[-1]["status"] == "success"


def test_builtin_failure_is_not_labeled_as_static_model_output() -> None:
    result = BuiltinProviderEngine()._failure_result(
        _task(),
        started=0.0,
        reason="provider_unavailable",
    )

    assert result.text == ""
    assert result.provider is None
    assert result.response_source == "model_unavailable"
    assert result.metadata["response_source"] == "model_unavailable"
    assert result.metadata["actual_provider"] is None
