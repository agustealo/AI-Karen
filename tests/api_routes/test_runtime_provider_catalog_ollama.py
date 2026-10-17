"""Chat catalog must reuse native Ollama inventory from Application Settings."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.models import runtime_api, settings as settings_routes


def _settings_payload() -> dict[str, object]:
    return {
        "providers": [{
            "id": "ollama",
            "display_name": "Ollama",
            "provider_type": "local",
            "enabled": True,
            "is_configured": True,
            "healthy": True,
            "selected_model": "goekdenizguelmez/JOSIEFIED-Qwen3:8b",
            "models": [{
                "id": "not-installed:latest",
                "name": "Old configured default",
                "is_installed": False,
            }],
        }],
        "selected_provider": "ollama",
        "selected_model": "goekdenizguelmez/JOSIEFIED-Qwen3:8b",
        "default_provider": "builtin_transformers",
        "default_model": "auto",
        "fallback_hierarchy": ["ollama"],
    }


@pytest.mark.asyncio
async def test_chat_catalog_lists_live_installed_ollama_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return _settings_payload()

    selected = "goekdenizguelmez/JOSIEFIED-Qwen3:8b"
    alt = "qwen2.5:7b"

    async def inventory(*, provider_id: str, current_user: object) -> dict[str, object]:
        assert provider_id == "ollama"
        return {
            "models": [
                settings_routes.ProviderModelPayload(
                    id=selected, name=selected, is_installed=True,
                ),
                settings_routes.ProviderModelPayload(
                    id=alt, name=alt, is_installed=True,
                ),
            ],
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "get_provider_models", inventory)
    current_user = SimpleNamespace(user_id="user-1", tenant_id="tenant-1")
    catalog = await runtime_api.get_runtime_provider_catalog(current_user=current_user)

    ollama = next(provider for provider in catalog.providers if provider.id == "ollama")
    assert {model.id for model in ollama.models} == {selected, alt}
    assert all(model.available for model in ollama.models)
    assert "not-installed:latest" not in [model.id for model in ollama.models]
    assert ollama.selected_model == selected
    assert catalog.default_provider == "ollama"
    assert catalog.default_model == selected


@pytest.mark.asyncio
async def test_chat_catalog_fails_closed_when_ollama_discovery_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return _settings_payload()

    async def unavailable(*, provider_id: str, current_user: object) -> dict[str, object]:
        raise HTTPException(status_code=503, detail="Native Ollama unavailable")

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "get_provider_models", unavailable)

    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    ollama = next(provider for provider in catalog.providers if provider.id == "ollama")
    assert ollama.models == []
    assert ollama.selected_model is None
    assert ollama.degradation_reason == "Ollama installed-model inventory unavailable"
    assert catalog.default_model == "auto"
    assert catalog.default_provider == "ollama"
