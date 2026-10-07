from __future__ import annotations

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import _resolve_base_url
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


def _endpoint(provider_id: str) -> ProviderEndpoint:
    return next(
        endpoint
        for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        if endpoint.provider_id == provider_id
    )


def test_local_runtime_environment_overrides_static_inventory_url(monkeypatch) -> None:
    endpoint = _endpoint("lmstudio-desktop")
    assert endpoint.base_url == "http://localhost:1234/v1"

    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1/")

    assert _resolve_base_url(endpoint) == "http://host.docker.internal:1234/v1"


def test_registered_endpoint_url_remains_authoritative_without_runtime_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LMSTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    endpoint = ProviderEndpoint(
        provider_id="tenant-openai-compatible",
        display_name="Tenant OpenAI-Compatible",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://model.internal:9000/v1/",
        runtime_engine=RuntimeEngine.CUSTOM,
    )

    assert _resolve_base_url(endpoint) == "http://model.internal:9000/v1"


def test_host_only_ollama_override_inherits_registered_openai_prefix(monkeypatch) -> None:
    endpoint = _endpoint("ollama-local")
    assert endpoint.base_url == "http://localhost:11434/v1"

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    assert _resolve_base_url(endpoint) == "http://host.docker.internal:11434/v1"


def test_explicit_ollama_override_path_remains_authoritative(monkeypatch) -> None:
    endpoint = _endpoint("ollama-local")

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/custom-openai/v1/")

    assert _resolve_base_url(endpoint) == "http://ollama:11434/custom-openai/v1"
