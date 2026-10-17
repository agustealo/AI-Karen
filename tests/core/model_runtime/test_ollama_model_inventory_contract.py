"""Ollama inventory and endpoint selection are owned by model runtime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.model_runtime.ollama_model_inventory import (
    discover_installed_ollama_models,
    resolve_ollama_inventory_endpoint,
)
from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


@pytest.mark.parametrize(
    ("runtime_source", "expected"),
    [
        ("host", "http://host.docker.internal:11434/v1"),
        ("container", "http://ollama:11434"),
    ],
)
def test_selected_runtime_source_controls_inventory_endpoint(
    runtime_source: str, expected: str,
) -> None:
    endpoint = resolve_ollama_inventory_endpoint(
        saved_base_url=None,
        configured_base_url="http://localhost:11434/v1",
        runtime_source=runtime_source,
        runtime_options=[
            {"source": "host", "available": True, "base_url": "http://host.docker.internal:11434/v1"},
            SimpleNamespace(source="container", available=True, base_url="http://ollama:11434"),
        ],
    )
    assert endpoint == expected


def test_explicit_saved_endpoint_takes_priority() -> None:
    assert resolve_ollama_inventory_endpoint(
        saved_base_url="http://configured-ollama:11434/v1",
        configured_base_url="http://localhost:11434/v1",
        runtime_source="container",
        runtime_options=[{"source": "container", "available": True, "base_url": "http://ollama:11434"}],
    ) == "http://configured-ollama:11434/v1"


def test_unavailable_selected_runtime_never_becomes_confirmed_inventory() -> None:
    assert resolve_ollama_inventory_endpoint(
        saved_base_url=None,
        configured_base_url="http://localhost:11434/v1",
        runtime_source="container",
        runtime_options=[{"source": "container", "available": False, "base_url": "http://ollama:11434"}],
    ) is None


@pytest.mark.asyncio
async def test_inventory_returns_exact_native_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ["goekdenizguelmez/JOSIEFIED-Qwen3:8b", "qwen2.5:7b"]
    monkeypatch.setattr(OllamaProvider, "get_models", lambda self: names)
    assert await discover_installed_ollama_models("http://localhost:11434/v1") == names


@pytest.mark.asyncio
async def test_unreachable_daemon_fails_without_saved_default_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(self: OllamaProvider) -> list[str]:
        raise ConnectionError("daemon unreachable")
    monkeypatch.setattr(OllamaProvider, "get_models", unavailable)
    with pytest.raises(ConnectionError, match="unreachable"):
        await discover_installed_ollama_models("http://localhost:11434/v1")
