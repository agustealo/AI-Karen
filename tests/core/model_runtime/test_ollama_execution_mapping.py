"""Ensure settings and endpoint identities resolve to the Ollama runtime."""

from __future__ import annotations

from ai_karen_engine.config.provider_execution_resolver import (
    resolve_provider_execution,
)


def test_configured_ollama_provider_resolves_explicitly() -> None:
    spec = resolve_provider_execution("ollama")
    assert spec is not None
    assert spec.provider_id == "ollama"
    assert spec.runtime_engine == "ollama"
    assert spec.execution_family == "openai_compatible"
    assert spec.adapter_class == "OpenAICompatibleProvider"
    assert "not explicitly mapped" not in spec.notes
