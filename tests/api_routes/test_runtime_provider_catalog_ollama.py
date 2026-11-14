"""Chat catalog must reuse native Ollama inventory from Application Settings."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ai_karen_engine.api_routes.models import runtime_api


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
            "runtime_source": "host",
            "runtime_options": [{
                "source": "host",
                "available": True,
                "base_url": "http://host.docker.internal:11434/v1",
            }],
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

    async def inventory(base_url: str) -> list[str]:
        assert base_url == "http://host.docker.internal:11434/v1"
        return [selected, alt]

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "discover_installed_ollama_models", inventory)
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

    async def unavailable(base_url: str) -> list[str]:
        raise ConnectionError("Native Ollama unavailable")

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "discover_installed_ollama_models", unavailable)

    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    ollama = next(provider for provider in catalog.providers if provider.id == "ollama")
    assert ollama.models == []
    assert ollama.selected_model is None
    assert ollama.degradation_reason == "Ollama installed-model inventory unavailable"
    assert ollama.healthy is False
    assert ollama.health.status == "degraded"
    assert catalog.default_model == "auto"
    assert catalog.default_provider == "ollama"


@pytest.mark.asyncio
async def test_settings_failure_never_advertises_unverified_bootstrap_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable() -> dict[str, object]:
        raise ConnectionError("Settings storage unavailable")

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", unavailable)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    assert catalog.catalog_version == "bootstrap"
    assert catalog.errors[0]["error_type"] == "settings_payload_failed"
    assert len(catalog.providers) == 1
    provider = catalog.providers[0]
    assert provider.configured is False
    assert provider.healthy is False
    assert provider.health.status == "degraded"
    assert provider.models == []
    assert provider.selected_model is None
    assert "unverified" in (provider.degradation_reason or "")


@pytest.mark.asyncio
async def test_empty_provider_settings_do_not_advertise_available_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty() -> dict[str, object]:
        return {"providers": []}

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", empty)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    assert catalog.catalog_version == "bootstrap"
    assert not any(model.available for provider in catalog.providers for model in provider.models)


@pytest.mark.asyncio
async def test_custom_manual_model_is_marked_configured_not_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "custom", "display_name": "Custom endpoint",
                "provider_type": "custom", "enabled": True,
                "is_configured": True, "healthy": True,
                "selected_model": "my-inference-model", "models": [],
            }],
            "selected_provider": "custom",
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = next(item for item in catalog.providers if item.id == "custom")
    assert len(provider.models) == 1
    assert provider.models[0].id == "my-inference-model"
    assert provider.models[0].source == "manual_configured"
    assert provider.models[0].available is False
    assert catalog.default_model == "auto"



@pytest.mark.asyncio
async def test_saved_custom_model_is_added_alongside_static_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "custom", "display_name": "Custom endpoint",
                "provider_type": "custom", "enabled": True,
                "is_configured": True, "healthy": True,
                "selected_model": "user-model",
                "models": [{
                    "id": "custom-model", "name": "Default catalog model",
                    "is_installed": False,
                }],
            }],
            "selected_provider": "custom",
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = next(item for item in catalog.providers if item.id == "custom")
    assert {model.id for model in provider.models} == {"custom-model", "user-model"}
    saved = next(model for model in provider.models if model.id == "user-model")
    assert saved.source == "manual_configured"
    assert saved.available is False
    assert provider.selected_model == "user-model"
    assert catalog.default_model == "auto"


@pytest.mark.asyncio
async def test_unconfigured_custom_provider_does_not_claim_saved_manual_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "custom", "display_name": "Custom endpoint",
                "provider_type": "custom", "enabled": True,
                "is_configured": False, "healthy": False,
                "selected_model": "user-model", "models": [],
            }],
            "selected_provider": "custom",
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = next(item for item in catalog.providers if item.id == "custom")
    assert provider.models == []
    assert provider.healthy is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observed_status", "credential_state", "expected_healthy"),
    [
        ("unknown", "not_required", False),
        ("healthy", "not_required", True),
        ("healthy", "missing", False),
        ("degraded", "configured", False),
        ("unhealthy", "configured", False),
    ],
)
async def test_canonical_health_and_configuration_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    observed_status: str,
    credential_state: str,
    expected_healthy: bool,
) -> None:
    """Unknown health and missing credentials cannot become executable claims."""
    from datetime import datetime, timezone

    from ai_karen_engine.api_routes.models import settings as model_settings
    from ai_karen_engine.config.llm_provider_config import ProviderType
    from ai_karen_engine.config import runtime_provider_manager
    from ai_karen_engine.core.model_runtime import provider_registry_service
    from ai_karen_engine.core.model_runtime.provider_health_monitor import (
        HealthStatus,
        ProviderHealthInfo,
    )

    provider = SimpleNamespace(
        name="builtin_transformers",
        display_name="Transformers",
        description="Local encoder-backed provider",
        provider_type=ProviderType.LOCAL,
        enabled=True,
        priority=1,
        models=[],
        capabilities={"chat"},
        authentication=None,
        endpoint=None,
        default_model="auto",
    )
    health = ProviderHealthInfo(
        provider_id="builtin_transformers",
        health_status=HealthStatus(observed_status),
        last_checked_at=(
            None if observed_status == "unknown"
            else datetime(2026, 11, 3, tzinfo=timezone.utc)
        ),
    )
    monkeypatch.setattr(
        model_settings, "get_settings_manager",
        lambda: SimpleNamespace(get_setting=lambda name, default=None: default),
    )
    monkeypatch.setattr(
        model_settings, "get_provider_config_manager",
        lambda: SimpleNamespace(list_providers=lambda: [provider]),
    )

    async def no_discovered_models(*, runtime: str) -> list[object]:
        return []

    monkeypatch.setattr(
        model_settings, "get_model_discovery_service",
        lambda: SimpleNamespace(get_models_async=no_discovered_models),
    )
    monkeypatch.setattr(model_settings, "_get_provider_override", lambda name: {})
    monkeypatch.setattr(
        model_settings, "_get_api_key_status",
        lambda name, item: credential_state,
    )
    monkeypatch.setattr(
        model_settings, "_supports_base_url_override", lambda item: False,
    )
    monkeypatch.setattr(
        model_settings, "get_provider_execution_spec", lambda name: {},
    )
    observed = []
    monkeypatch.setattr(
        provider_registry_service,
        "get_provider_registry_service",
        lambda: SimpleNamespace(
            canonicalize_provider_id=lambda provider_id: provider_id,
            health_monitor=SimpleNamespace(
                get_provider_health=lambda provider_id: (
                    observed.append(provider_id) or health
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        runtime_provider_manager, "get_runtime_provider_manager",
        lambda: pytest.fail("Legacy health manager must not be used by settings"),
    )
    payload = await model_settings.build_model_settings_payload()
    assert len(payload["providers"]) == 1
    item = payload["providers"][0]
    assert item.healthy is expected_healthy
    assert item.health_status == observed_status
    assert (item.health_last_checked_at is None) is (observed_status == "unknown")
    assert item.is_configured is (credential_state in {"configured", "not_required"})
    assert observed == ["builtin_transformers"]

    async def payload_for_catalog() -> dict[str, object]:
        return payload

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload_for_catalog)
    catalog = await runtime_api.get_runtime_provider_catalog(
        current_user={"roles": ["admin"]}
    )
    runtime = catalog.providers[0]
    assert runtime.healthy is expected_healthy
    assert runtime.health.status == observed_status
    assert (runtime.health.last_checked_at is None) is (observed_status == "unknown")
    assert runtime.models == []


@pytest.mark.asyncio
async def test_runtime_catalog_distinguishes_real_failure_from_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [
                {
                    "id": "ollama",
                    "display_name": "Ollama",
                    "provider_type": "local",
                    "enabled": True,
                    "is_configured": True,
                    "healthy": False,
                    "health_status": "unavailable",
                    "degraded_reason": "Selected Ollama runtime is unavailable",
                    "models": [],
                },
                {
                    "id": "openai",
                    "display_name": "OpenAI",
                    "provider_type": "remote",
                    "enabled": True,
                    "is_configured": True,
                    "healthy": False,
                    "health_status": "unhealthy",
                    "models": [],
                },
            ],
            "selected_provider": "ollama",
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    catalog = await runtime_api.get_runtime_provider_catalog(
        current_user={"roles": ["admin"]}
    )
    assert {entry.id: entry.health.status for entry in catalog.providers} == {
        "ollama": "unavailable", "openai": "unhealthy"
    }
    assert all(entry.healthy is False for entry in catalog.providers)


@pytest.mark.asyncio
async def test_remote_provider_requires_live_models_before_chat_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a healthy connection with provider-reported model IDs is chat ready."""
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "openai",
                "display_name": "OpenAI",
                "provider_type": "external",
                "enabled": True,
                "is_configured": True,
                "healthy": True,
                "health_status": "healthy",
                "selected_model": "gpt-live",
                "models": [{"id": "catalog-only", "name": "Catalog", "is_installed": False}],
            }],
            "selected_provider": "openai",
        }

    async def live_models(name: str, *, current_user) -> dict[str, object]:
        assert name == "openai"
        assert current_user == {"roles": ["admin"]}
        return {
            "models": [
                {"id": "gpt-live", "name": "Provider observed", "source": "provider_live"},
                {"id": "catalog-only", "name": "Catalog", "source": "configured_catalog", "is_installed": False},
            ],
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "get_provider_models", live_models)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = catalog.providers[0]
    assert provider.healthy is True
    assert {model.id for model in provider.models if model.available} == {"gpt-live"}
    assert catalog.default_model == "gpt-live"
    assert any(model.id == "catalog-only" and not model.available for model in provider.models)


@pytest.mark.asyncio
async def test_remote_catalog_outage_fails_closed_even_after_previous_good_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "openai",
                "display_name": "OpenAI",
                "provider_type": "external",
                "enabled": True,
                "is_configured": True,
                "healthy": True,
                "health_status": "healthy",
                "selected_model": "configured-model",
                "models": [{"id": "configured-model", "name": "Static", "is_installed": False}],
            }],
            "selected_provider": "openai",
        }

    async def unavailable(name: str, *, current_user):
        raise ConnectionError("Provider unavailable")

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    monkeypatch.setattr(runtime_api, "get_provider_models", unavailable)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = catalog.providers[0]
    assert provider.healthy is False
    assert provider.models == []
    assert provider.health.status == "degraded"
    assert catalog.default_model == "auto"


@pytest.mark.asyncio
async def test_local_model_cannot_be_chat_ready_without_configured_healthy_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload() -> dict[str, object]:
        return {
            "providers": [{
                "id": "builtin_transformers",
                "display_name": "Transformers",
                "provider_type": "builtin",
                "enabled": True,
                "is_configured": False,
                "healthy": False,
                "health_status": "unknown",
                "models": [{
                    "id": "weights-on-disk",
                    "name": "Unverified weights",
                    "is_installed": True,
                    "source": "local_runtime",
                }],
            }],
            "selected_provider": "builtin_transformers",
        }

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", payload)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    provider = catalog.providers[0]
    assert provider.models[0].available is False
    assert catalog.default_model == "auto"


@pytest.mark.asyncio
async def test_runtime_catalog_outage_does_not_expose_secret_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable():
        raise RuntimeError("provider://admin:private-token@internal.invalid?key=private-token")

    monkeypatch.setattr(runtime_api, "build_model_settings_payload", unavailable)
    catalog = await runtime_api.get_runtime_provider_catalog(current_user={"roles": ["admin"]})
    assert catalog.catalog_version == "bootstrap"
    assert "private-token" not in catalog.model_dump_json()
    assert catalog.errors[0]["error_type"] == "settings_payload_failed"
