"""External compatibility transports must fail closed without RuntimePolicy grants.

This covers direct client access, not merely ModelManager's ordinary chat path.
A guarded HTTP opener does not itself authorize network egress or spend budget.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.model_runtime import openai_compatible_client as client_module
from ai_karen_engine.core.model_runtime.openai_compatible_client import (
    OpenAICompatibleRuntimeClient,
)
from ai_karen_engine.core.model_runtime.provider_contracts import (
    EmbeddingFailed,
    ProviderNotAvailable,
)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "http://unregistered-model.example.test/v1",
        "http://198.51.100.25:8000/v1",
        "http://user:password@127.0.0.1:8000/v1",
        "https://127.0.0.1:8000/v1?unsafe=true",
    ],
)
def test_unscoped_remote_compatibility_transport_has_zero_wire_calls(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    attempts: list[object] = []

    def blocked_opener(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("Denied inference must not issue HTTP")

    monkeypatch.setattr(client_module, "_open_provider_request", blocked_opener)
    client = OpenAICompatibleRuntimeClient(
        model="any-model",
        base_url=base_url,
        provider_name="ollama-local",  # A local-looking name grants no authority.
        api_key="never-should-leak",
        timeout_seconds=1,
    )

    with pytest.raises(
        ProviderNotAvailable,
        match="ungoverned_external_compatibility_transport_denied",
    ):
        client.generate_text("confidential prompt")
    with pytest.raises(ProviderNotAvailable):
        client.generate_response("confidential prompt")
    with pytest.raises(ProviderNotAvailable):
        list(client.stream_generate("confidential prompt"))
    with pytest.raises(EmbeddingFailed):
        client.embed("confidential input")
    with pytest.raises(ProviderNotAvailable):
        client._request("/chat/completions", {"messages": []})

    health = client.health_check()
    assert health["status"] == "unhealthy"
    assert health["provider"] == "ollama-local"
    assert health["error"] == "ungoverned_external_compatibility_transport_denied"
    assert attempts == []


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:1234/v1",
        "http://[::1]:1234/v1",
        "http://host.docker.internal:11434/v1",
    ],
)
def test_compatibility_locality_uses_existing_canonical_classifier(
    base_url: str,
) -> None:
    client = OpenAICompatibleRuntimeClient(
        model="local-model",
        base_url=base_url,
        provider_name="local",
    )
    client._require_local_compatibility_transport()


def test_rebinding_base_url_to_external_is_checked_on_each_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def blocked_opener(*args, **kwargs):
        calls.append("wire")
        raise AssertionError("Transport should not be reached")

    monkeypatch.setattr(client_module, "_open_provider_request", blocked_opener)
    client = OpenAICompatibleRuntimeClient(
        model="local-model",
        base_url="http://127.0.0.1:11434/v1",
        provider_name="ollama-local",
    )
    client._require_local_compatibility_transport()
    client.base_url = "https://remote-model.example.test/v1"

    with pytest.raises(ProviderNotAvailable):
        client.generate_text("confidential")
    assert calls == []

@pytest.mark.asyncio
async def test_inference_port_cannot_turn_ungoverned_external_model_into_wire_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.model_runtime import model_manager as manager_module
    from ai_karen_engine.core.model_runtime.inference_port import (
        InferenceRequest,
        ModelManagerInferencePort,
    )
    from ai_karen_engine.core.model_runtime.model_manager import (
        ModelManager,
        RuntimeSelection,
    )
    from ai_karen_engine.core.model_runtime.provider_endpoint import (
        ProviderEndpointType,
    )

    attempts: list[str] = []

    def blocked_opener(*args, **kwargs):
        attempts.append("http")
        raise AssertionError("Inference port attempted unauthorized egress")

    monkeypatch.setattr(client_module, "_open_provider_request", blocked_opener)
    client = OpenAICompatibleRuntimeClient(
        model="external-model",
        base_url="https://remote-model.example.test/v1",
        provider_name="ollama-local",
    )
    selection = RuntimeSelection(
        provider_id="ollama-local",
        display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="external-model",
        base_url=client.base_url,
    )
    manager = object.__new__(ModelManager)
    monkeypatch.setattr(
        manager,
        "select_provider",
        lambda _capability, *, context=None, stream=False: selection,
    )
    monkeypatch.setattr(manager, "resolve_runtime", lambda _selection: client)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _provider_id: True)
    monkeypatch.setattr(
        manager,
        "_get_breaker",
        lambda _provider_id: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_record_provider_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager_module, "get_model_manager", lambda: manager)

    with pytest.raises(
        ProviderNotAvailable,
        match="ungoverned_external_compatibility_transport_denied",
    ):
        await ModelManagerInferencePort().generate(
            InferenceRequest(
                messages=[{"role": "user", "content": "private prompt"}],
                preferred_provider="ollama-local",
            )
        )
    assert attempts == []
