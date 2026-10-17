"""Regression proof for Ollama native model inventory endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("http://host.docker.internal:11434", "http://host.docker.internal:11434/api"),
        ("http://host.docker.internal:11434/v1", "http://host.docker.internal:11434/api"),
        ("http://host.docker.internal:11434/v1/", "http://host.docker.internal:11434/api"),
        ("http://ollama:11434", "http://ollama:11434/api"),
        ("http://ollama:11434/api", "http://ollama:11434/api"),
    ],
)
def test_ollama_native_api_normalization(configured: str, expected: str) -> None:
    assert OllamaProvider._normalize_base_url(configured) == expected


def test_all_installed_ollama_models_are_returned_with_exact_tags() -> None:
    provider = OllamaProvider(
        base_url="http://host.docker.internal:11434/v1",
        max_retries=0,
    )
    requested_urls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "models": [
                    {"name": "deepseek-r1:1.5b"},
                    {"name": "qwen2.5:7b"},
                    {"model": "llama3.2:latest"},
                ]
            }

    provider._requests = SimpleNamespace(
        get=lambda url, timeout: (requested_urls.append(url), Response())[1],
        exceptions=SimpleNamespace(RequestException=Exception),
    )

    assert provider.get_models() == [
        "deepseek-r1:1.5b",
        "qwen2.5:7b",
        "llama3.2:latest",
    ]
    assert requested_urls == ["http://host.docker.internal:11434/api/tags"]
