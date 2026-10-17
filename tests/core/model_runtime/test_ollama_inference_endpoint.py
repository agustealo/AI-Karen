"""OpenAI-compatible Ollama inference must use /v1, not the native /api root."""

from __future__ import annotations

import pytest

from ai_karen_engine.integrations.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from ai_karen_engine.integrations.providers.openai_provider import OpenAIProvider


@pytest.mark.parametrize("provider_id", ["ollama", "ollama-local"])
@pytest.mark.parametrize(
    "configured",
    [
        "http://host.docker.internal:11434",
        "http://host.docker.internal:11434/",
        "http://host.docker.internal:11434/api",
        "http://host.docker.internal:11434/v1",
        "http://host.docker.internal:11434/v1/",
    ],
)
def test_ollama_inference_url_is_normalized_before_sdk_initialization(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    configured: str,
) -> None:
    captured: list[str] = []

    def capture_sdk_url(self: OpenAIProvider) -> None:
        captured.append(self.base_url)

    monkeypatch.setattr(OpenAIProvider, "_initialize_client", capture_sdk_url)
    adapter = OpenAICompatibleProvider(
        provider_name=provider_id,
        model="qwen2.5:7b",
        base_url=configured,
        max_retries=0,
    )
    assert adapter.base_url == "http://host.docker.internal:11434/v1"
    assert captured == [adapter.base_url]
    assert adapter.model == "qwen2.5:7b"


def test_non_ollama_compatible_endpoint_keeps_its_original_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(OpenAIProvider, "_initialize_client", lambda self: None)
    adapter = OpenAICompatibleProvider(
        provider_name="custom",
        model="a-model",
        base_url="https://custom.example.com/openai/v1",
    )
    assert adapter.base_url == "https://custom.example.com/openai/v1"
