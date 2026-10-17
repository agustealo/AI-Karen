"""Authorized provider model inventory and settings response contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.models import settings as settings_routes
from ai_karen_engine.config.llm_provider_config import ProviderType
from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


@pytest.fixture
def ollama_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(
        name="ollama",
        enabled=True,
        endpoint=SimpleNamespace(base_url="http://host.docker.internal:11434"),
        provider_type=ProviderType.LOCAL,
        models=[SimpleNamespace(
            id="not-installed:latest",
            name="Not installed",
            family="ollama",
            capabilities=[],
        )],
    )
    manager = SimpleNamespace(get_provider=lambda name: provider if name == "ollama" else None)
    monkeypatch.setattr(settings_routes, "get_provider_config_manager", lambda: manager)
    monkeypatch.setattr(settings_routes, "_get_provider_override", lambda name: {})
    async def runtime_options():
        return []
    monkeypatch.setattr(settings_routes, "_get_ollama_runtime_options", runtime_options)


@pytest.mark.parametrize("base_url", [
    "http://host.docker.internal:11434",
    "http://host.docker.internal:11434/v1",
    "http://host.docker.internal:11434/api",
])
@pytest.mark.asyncio
async def test_ollama_inventory_uses_selected_authorized_endpoint(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    monkeypatch.setattr(
        OllamaProvider,
        "get_models",
        lambda self: ["deepseek-r1:1.5b", "qwen2.5:7b"],
    )
    result = await settings_routes.get_provider_models(
        "ollama", base_url=base_url, current_user={"roles": ["admin"]},
    )
    assert [item.id for item in result["models"]] == ["deepseek-r1:1.5b", "qwen2.5:7b"]
    assert all(item.is_installed for item in result["models"])
    assert "not-installed:latest" not in [item.id for item in result["models"]]


@pytest.mark.asyncio
async def test_discovery_rejects_unapproved_targets(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OllamaProvider, "get_models",
        lambda self: pytest.fail("Untrusted endpoint must never be contacted"),
    )
    with pytest.raises(HTTPException) as exc:
        await settings_routes.get_provider_models(
            "ollama",
            base_url="http://127.0.0.1:5432",
            current_user={"roles": ["admin"]},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ollama_outage_is_not_rendered_as_fake_installed_models(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(self) -> list[str]:
        raise RuntimeError("Cannot reach Ollama")

    monkeypatch.setattr(OllamaProvider, "get_models", unreachable)
    with pytest.raises(HTTPException) as exc:
        await settings_routes.get_provider_models(
            "ollama",
            base_url="http://host.docker.internal:11434",
            current_user={"roles": ["admin"]},
        )
    assert exc.value.status_code == 503


def test_settings_contract_accepts_runtime_and_response_modes() -> None:
    request = settings_routes.ModelSettingsUpdateRequest(
        provider="ollama",
        model="deepseek-r1:1.5b",
        runtime_source="host",
        chat_response_mode="streaming_first",
    )
    assert request.runtime_source == "host"
    assert request.chat_response_mode == "streaming_first"
