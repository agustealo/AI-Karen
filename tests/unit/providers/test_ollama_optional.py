from __future__ import annotations

import pytest

from ai_karen_engine.integrations.llm_utils import GenerationFailed
from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


def test_ollama_uses_explicit_provider_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    provider = OllamaProvider(
        model="example",
        base_url="https://ollama.example.test",
    )

    assert provider.provider_name == "ollama"
    assert provider.base_url == "https://ollama.example.test/api"


def test_ollama_can_take_endpoint_from_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    provider = OllamaProvider(model="example")

    assert provider.base_url == "http://localhost:11434/api"


def test_ollama_does_not_invent_endpoint_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    provider = OllamaProvider(model="example")

    assert provider.base_url == ""
    assert provider._requests is None

    with pytest.raises(GenerationFailed, match="no configured base URL"):
        provider.get_models()

    with pytest.raises(GenerationFailed, match="no configured base URL"):
        provider.generate_text("hello")


def test_ollama_has_no_provider_specific_enablement_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARI_OLLAMA_ENABLED", "false")

    provider = OllamaProvider(
        model="example",
        base_url="http://localhost:11434",
    )

    assert not hasattr(provider, "enabled")
    assert provider.base_url == "http://localhost:11434/api"
