"""Ollama inventory and endpoint selection are owned by model runtime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.model_runtime.ollama_model_inventory import (
    resolve_ollama_inventory_endpoint,
)
from ai_karen_engine.integrations.providers.ollama_provider import (
    discover_installed_ollama_models,
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


@pytest.mark.parametrize(
    ("done_reason", "expected_truncated"),
    [("stop", False), ("length", True), (None, False)],
)
def test_ollama_native_completion_reason_is_preserved(
    done_reason: str | None,
    expected_truncated: bool,
) -> None:
    provider = OllamaProvider(model="qwen3:4b", base_url="http://localhost:11434")
    provider._record_usage({
        "prompt_eval_count": 12,
        "eval_count": 24,
        "done_reason": done_reason,
    })
    assert provider.last_usage["input_tokens"] == 12
    assert provider.last_usage["output_tokens"] == 24
    assert provider.last_usage["finish_reason"] == done_reason
    assert provider.last_usage["output_truncated"] is expected_truncated


@pytest.mark.parametrize(
    ("done_reason", "truncated"),
    [("stop", False), ("length", True)],
)
def test_ollama_generate_text_records_native_completion_outcome(
    monkeypatch: pytest.MonkeyPatch,
    done_reason: str,
    truncated: bool,
) -> None:
    provider = OllamaProvider(model="qwen3:4b", base_url="http://localhost:11434")
    monkeypatch.setattr(provider, "_request", lambda path, payload: {
        "message": {"content": "Partial model output"},
        "prompt_eval_count": 7,
        "eval_count": 18,
        "done_reason": done_reason,
    })
    assert provider.generate_text([{"role": "user", "content": "Explain this"}]) == "Partial model output"
    assert provider.last_usage["finish_reason"] == done_reason
    assert provider.last_usage["output_truncated"] is truncated
