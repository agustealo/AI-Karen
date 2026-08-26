from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.expression.engines import OpenAICompatibleEngine
from ai_karen_engine.core.expression.registry import get_engine
from ai_karen_engine.core.expression.settings import ExpressionSettings
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_policy import evaluate_provider_policy
from ai_karen_engine.core.model_runtime.runtime_engine import EndpointProtocol


ROOT = Path(__file__).resolve().parents[2]
EXPRESSION_ENGINES = ROOT / "src/ai_karen_engine/core/expression/engines"
MODEL_PROVIDERS = ROOT / "src/ai_karen_engine/core/model_runtime/providers"


def test_expression_defaults_are_provider_agnostic_local_first() -> None:
    settings = ExpressionSettings()

    assert settings.active_engine == "local"
    assert settings.engine_fallback_order == ["local", "cloud"]
    assert "builtin" not in settings.engines
    assert settings.engines["local"].type == "openai_compatible"
    assert settings.engines["cloud"].type == "openai_compatible"


def test_legacy_builtin_engine_id_resolves_to_local_openai_compatible_engine() -> None:
    engine = get_engine("builtin")

    assert isinstance(engine, OpenAICompatibleEngine)
    assert engine.engine_id == "local"


def test_builtin_vllm_is_deprecated_to_generic_openai_compatible_provider() -> None:
    decision = evaluate_provider_policy("builtin_vllm")

    assert decision.allowed is False
    assert decision.classification == "deprecated_provider_alias"
    assert decision.replacement == "custom_openai_compatible"


def test_vllm_runtime_name_is_not_a_provider_identity() -> None:
    decision = evaluate_provider_policy("vllm")

    assert decision.allowed is False
    assert decision.classification == "deprecated_provider_alias"
    assert decision.replacement == "custom_openai_compatible"


def test_transformers_is_specialized_ml_not_chat_provider() -> None:
    endpoints = {endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS}
    transformers = endpoints["builtin_transformers"]

    assert transformers.endpoint_type is ProviderEndpointType.BUILTIN_TRANSFORMERS
    assert transformers.protocol is EndpointProtocol.NATIVE
    assert transformers.fallback_eligible is False
    assert "chat_completion" not in transformers.capabilities
    assert "text_generation" not in transformers.capabilities
    assert "embeddings" in transformers.capabilities
    assert "classification" in transformers.capabilities


def test_local_chat_endpoints_are_openai_compatible() -> None:
    endpoints = {endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS}

    for provider_id in ("lmstudio-desktop", "ollama-local", "llamacpp-server"):
        endpoint = endpoints[provider_id]
        assert endpoint.endpoint_type is ProviderEndpointType.OPENAI_COMPATIBLE
        assert endpoint.protocol is EndpointProtocol.OPENAI_COMPATIBLE
        assert "chat_completion" in endpoint.capabilities
        assert "text_generation" in endpoint.capabilities
        assert endpoint.fallback_eligible is True


def test_retired_builtin_provider_engine_is_not_exported_or_present() -> None:
    init_source = (EXPRESSION_ENGINES / "__init__.py").read_text(encoding="utf-8")
    registry_source = (
        ROOT / "src/ai_karen_engine/core/expression/registry.py"
    ).read_text(encoding="utf-8")

    assert "BuiltinProviderEngine" not in init_source
    assert "BuiltinProviderEngine" not in registry_source
    assert "builtin_provider_engine" not in registry_source
    assert not (EXPRESSION_ENGINES / "builtin_provider_engine.py").exists()


def test_retired_core_vllm_wrapper_is_not_present() -> None:
    providers_init = (MODEL_PROVIDERS / "__init__.py").read_text(encoding="utf-8")

    assert "VLLMRuntime" not in providers_init
    assert "vllm_runtime" not in providers_init
    assert not (MODEL_PROVIDERS / "vllm_runtime.py").exists()
