from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.expression.engines.openai_compatible_engine import (
    OpenAICompatibleEngine,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import ProviderExecutionResult
from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)


REQUIRED_GENERATIVE_CAPABILITIES = {"chat_completion", "text_generation"}


def _task(preferred_provider: str = "auto") -> ExpressionTask:
    return ExpressionTask(
        task_id="beta-proof",
        kind="chat",
        messages=[{"role": "user", "content": "Return BETA_PROVIDER_WIRING_OK"}],
        response_mode="text",
        required_capabilities=["chat_completion"],
        forbidden_capabilities=[],
        preferred_provider=preferred_provider,
        preferred_model="beta-model",
        max_tokens=32,
        temperature=0.0,
        timeout_ms=5000,
        correlation_id="beta-correlation",
        request_id="beta-request",
    )


def _custom_vllm_endpoint() -> ProviderEndpoint:
    return ProviderEndpoint(
        provider_id="beta-vllm-openai-compatible",
        display_name="Beta vLLM OpenAI-Compatible Endpoint",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:8000/v1",
        enabled=True,
        builtin=False,
        tenant_scoped=True,
        timeout_seconds=5.0,
        supports_streaming=True,
        supports_embeddings=False,
        supports_models_endpoint=True,
        fallback_eligible=True,
        capabilities=("chat_completion", "text_generation", "streaming"),
        default_model="beta-model",
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        runtime_engine=RuntimeEngine.VLLM,
        locality=Locality.LOCAL,
        metadata={"priority": 1},
    )


def test_local_generative_endpoints_use_canonical_capabilities() -> None:
    endpoints = {endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS}

    for provider_id in ("lmstudio-desktop", "ollama-local", "llamacpp-server"):
        endpoint = endpoints[provider_id]
        assert REQUIRED_GENERATIVE_CAPABILITIES.issubset(
            {capability.lower() for capability in endpoint.capabilities}
        )
        assert endpoint.base_url
        assert endpoint.fallback_eligible is True
        assert endpoint.protocol is EndpointProtocol.OPENAI_COMPATIBLE


@pytest.mark.asyncio
@pytest.mark.parametrize("preferred_provider", ["auto", "beta-vllm-openai-compatible"])
async def test_openai_compatible_provider_executes_registered_vllm_endpoint_and_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
    preferred_provider: str,
) -> None:
    from ai_karen_engine.core.expression.engines import openai_compatible_engine as module

    endpoint = _custom_vllm_endpoint()

    class FakeRegistry:
        @staticmethod
        def canonicalize_provider_id(provider_id: str):
            return provider_id

        def get_provider_endpoint(self, provider_id: str):
            return endpoint if provider_id == endpoint.provider_id else None

        def get_provider_status(self, provider_id: str):
            assert provider_id == endpoint.provider_id
            return SimpleNamespace(is_available=True)

        def resolve_capable_targets(self, *, required_capabilities, healthy_only):
            assert required_capabilities == REQUIRED_GENERATIVE_CAPABILITIES
            assert healthy_only is True
            return [endpoint]

    registry_module = ModuleType(
        "ai_karen_engine.core.model_runtime.provider_registry_service"
    )
    registry_module.get_provider_registry_service = lambda: FakeRegistry()
    monkeypatch.setitem(
        sys.modules,
        "ai_karen_engine.core.model_runtime.provider_registry_service",
        registry_module,
    )

    async def fake_execute_provider_endpoint(target, **kwargs):
        assert target is endpoint
        assert target.endpoint_type is ProviderEndpointType.OPENAI_COMPATIBLE
        assert target.protocol is EndpointProtocol.OPENAI_COMPATIBLE
        assert target.runtime_engine is RuntimeEngine.VLLM
        assert kwargs["messages"] == _task(preferred_provider).messages
        assert kwargs["model"] == "beta-model"
        assert kwargs["max_tokens"] == 32
        assert kwargs["temperature"] == 0.0
        return ProviderExecutionResult(
            text="BETA_PROVIDER_WIRING_OK",
            model="beta-model",
            provider_id=endpoint.provider_id,
            runtime_engine="vllm",
        )

    monkeypatch.setattr(module, "execute_provider_endpoint", fake_execute_provider_endpoint)

    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    result = await engine.generate(_task(preferred_provider))

    assert result.text == "BETA_PROVIDER_WIRING_OK"
    assert result.provider == endpoint.provider_id
    assert result.model == "beta-model"
    assert result.runtime_engine == "vllm"
    assert result.engine_mode == "openai_compatible"
    assert result.response_source == "provider_runtime"
    assert result.degraded is False
    assert result.metadata["requested_provider"] == preferred_provider
    assert result.metadata["actual_provider"] == endpoint.provider_id
    assert result.metadata["actual_model"] == "beta-model"
    assert result.metadata["runtime_engine"] == "vllm"
    assert result.metadata["fallback_level"] == 0
    assert result.metadata["degraded_mode"] is False
    assert result.attempts[-1]["status"] == "success"

    # Core executes the endpoint contract directly. It does not need a vLLM
    # provider implementation or the legacy integration registry.
    assert "ai_karen_engine.integrations.llm_registry" not in sys.modules


def test_openai_compatible_failure_is_honest_model_unavailability() -> None:
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    result = engine._failure_result(
        _task("beta-vllm-openai-compatible"),
        started=0.0,
        reason="provider_unavailable",
        provider="beta-vllm-openai-compatible",
        requested_provider="beta-vllm-openai-compatible",
    )

    assert result.text == ""
    assert result.provider is None
    assert result.response_source == "model_unavailable"
    assert result.degraded is True
    assert result.degradation_reason == "provider_unavailable"
    assert result.engine_mode == "openai_compatible"
    assert result.metadata["requested_provider"] == "beta-vllm-openai-compatible"
    assert result.metadata["actual_provider"] is None
    assert result.metadata["fallback_level"] == 99
