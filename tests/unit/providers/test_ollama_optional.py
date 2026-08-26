from __future__ import annotations

import pytest

from ai_karen_engine.integrations.llm_utils import GenerationFailed
from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


def test_ollama_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARI_OLLAMA_ENABLED", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.invalid:11434")

    provider = OllamaProvider(model="example")

    assert provider.enabled is False
    assert provider.health_check() == {
        "status": "disabled",
        "provider": "ollama",
        "enabled": False,
    }
    assert provider._requests is None

    with pytest.raises(GenerationFailed, match="disabled"):
        provider.get_models()

    with pytest.raises(GenerationFailed, match="disabled"):
        provider.generate_text("hello")


def test_ollama_enablement_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    provider = OllamaProvider(model="example")

    assert provider.enabled is True
    assert provider.base_url == "http://localhost:11434/api"


def test_disabled_ollama_does_not_invent_a_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KARI_OLLAMA_ENABLED", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    provider = OllamaProvider(model="example")

    assert provider.enabled is False
    assert provider.base_url == ""
