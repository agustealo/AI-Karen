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


@pytest.mark.asyncio
async def test_ollama_runtime_source_and_response_mode_are_durably_saved(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict[str, object] = {}
    saved: list[bool] = []
    settings = SimpleNamespace(
        set_setting=lambda key, value, save=False: stored.__setitem__(key, value),
        _save_settings=lambda: saved.append(True),
    )
    monkeypatch.setattr(settings_routes, "get_settings_manager", lambda: settings)
    monkeypatch.setattr(
        settings_routes, "get_registry",
        lambda: SimpleNamespace(invalidate_provider_cache=lambda name: None),
    )

    async def live_host():
        return [settings_routes.RuntimeOptionPayload(
            source="host",
            label="Local host",
            available=True,
            base_url="http://host.docker.internal:11434",
            status="Online",
            message="Available",
        )]

    async def settings_response():
        return {"saved": True}

    monkeypatch.setattr(settings_routes, "_get_ollama_runtime_options", live_host)
    monkeypatch.setattr(settings_routes, "build_model_settings_payload", settings_response)

    result = await settings_routes.update_model_settings(
        settings_routes.ModelSettingsUpdateRequest(
            provider="ollama",
            model="qwen2.5:7b",
            runtime_source="host",
            chat_response_mode="non_streaming",
        ),
        current_user={"roles": ["admin"]},
    )

    assert result == {"saved": True}
    assert stored["provider"] == "ollama"
    assert stored["model"] == "qwen2.5:7b"
    assert stored["model_providers.ollama.runtime_source"] == "host"
    assert stored["chat_response_mode"] == "non_streaming"
    assert saved == [True]


@pytest.mark.asyncio
async def test_connection_settings_save_never_switches_workspace_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuring an individual provider is not a request to change routing."""
    writes: dict[str, object] = {}
    commits: list[bool] = []
    monkeypatch.setattr(
        settings_routes,
        "get_settings_manager",
        lambda: SimpleNamespace(
            set_setting=lambda key, value, save=False: writes.__setitem__(key, value),
            _save_settings=lambda: commits.append(True),
        ),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(),
    )

    async def saved():
        return {"selected_provider": "ollama", "selected_model": "qwen3:4b"}

    monkeypatch.setattr(settings_routes, "build_model_settings_payload", saved)
    result = await settings_routes.update_model_settings(
        settings_routes.ModelSettingsUpdateRequest(
            provider="openai", chat_response_mode="auto"
        ),
        current_user={"roles": ["admin"]},
    )
    assert result == {"selected_provider": "ollama", "selected_model": "qwen3:4b"}
    assert writes == {"chat_response_mode": "auto"}
    assert commits == [True]


@pytest.mark.asyncio
async def test_unavailable_runtime_is_rejected_before_persistence(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed: list[str] = []
    monkeypatch.setattr(
        settings_routes,
        "get_settings_manager",
        lambda: SimpleNamespace(set_setting=lambda key, value, save=False: changed.append(key)),
    )
    async def unavailable_host():
        return [settings_routes.RuntimeOptionPayload(
            source="host",
            label="Local host",
            available=False,
            base_url="http://host.docker.internal:11434",
            status="Offline",
            message="Not detected",
        )]

    monkeypatch.setattr(settings_routes, "_get_ollama_runtime_options", unavailable_host)
    with pytest.raises(HTTPException) as exc:
        await settings_routes.update_model_settings(
            settings_routes.ModelSettingsUpdateRequest(
                provider="ollama",
                model="qwen2.5:7b",
                runtime_source="host",
            ),
            current_user={"roles": ["admin"]},
        )
    assert exc.value.status_code == 409
    assert changed == []



@pytest.mark.parametrize(
    "provided,expected",
    [
        ("ollama", "ollama"),
        ("amazon-nova", "amazon-nova"),
        ("gmi-cloud", "gmi-cloud"),
        ("builtin_transformers", "builtin_transformers"),
        ("My Custom", "my_custom"),
    ],
)
def test_provider_ids_preserve_registered_names(provided: str, expected: str) -> None:
    assert settings_routes._normalize_provider_id(provided) == expected


@pytest.mark.asyncio
async def test_hyphenated_provider_selection_persists_under_canonical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict[str, object] = {}
    saved: list[bool] = []
    monkeypatch.setattr(
        settings_routes,
        "get_settings_manager",
        lambda: SimpleNamespace(
            set_setting=lambda key, value, save=False: stored.__setitem__(key, value),
            _save_settings=lambda: saved.append(True),
        ),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_registry",
        lambda: SimpleNamespace(invalidate_provider_cache=lambda provider: None),
    )

    async def settings_response() -> dict[str, bool]:
        return {"saved": True}

    monkeypatch.setattr(settings_routes, "build_model_settings_payload", settings_response)
    result = await settings_routes.update_model_settings(
        settings_routes.ModelSettingsUpdateRequest(
            provider="gmi-cloud", model="meta-llama/Llama-3.1-70B-Instruct",
        ),
        current_user={"roles": ["admin"]},
    )

    assert result == {"saved": True}
    assert stored["provider"] == "gmi-cloud"
    assert stored["model_providers.gmi-cloud.last_model"] == "meta-llama/Llama-3.1-70B-Instruct"
    assert saved == [True]


@pytest.mark.asyncio
async def test_remote_provider_discovery_tracks_live_and_configured_model_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.model_runtime import provider_execution

    provider = SimpleNamespace(
        name="gmi-cloud",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.gmi-serving.com/v1"),
        provider_type=ProviderType.REMOTE,
        models=[
            SimpleNamespace(id="catalog-only", name="Catalog only", family="cloud", capabilities=[]),
            SimpleNamespace(id="live-model", name="Catalog name", family="cloud", capabilities=[]),
        ],
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(
            get_provider=lambda name: provider if name == "gmi-cloud" else None,
            get_api_key=lambda name: None,
        ),
    )
    monkeypatch.setattr(settings_routes, "_get_provider_override", lambda name: {})

    async def no_local_models(*, runtime: str) -> list[object]:
        return []

    monkeypatch.setattr(
        settings_routes, "get_model_discovery_service",
        lambda: SimpleNamespace(get_models_async=no_local_models),
    )

    def remote_catalog(base_url, *, api_key):
        assert base_url == "https://api.gmi-serving.com/v1"
        assert api_key is None
        return ["live-model", "new-live-model"]

    monkeypatch.setattr(provider_execution, "discover_openai_compatible_model_ids", remote_catalog)
    response = await settings_routes.get_provider_models(
        "gmi-cloud", current_user={"roles": ["admin"]},
    )

    assert response["discovery_status"] == "ready"
    assert response["inventory_source"] == "mixed"
    assert response["live_discovery_failed"] is False
    by_id = {model.id: model for model in response["models"]}
    assert by_id["catalog-only"].source == "configured_catalog"
    assert by_id["live-model"].source == "provider_live"
    assert by_id["new-live-model"].source == "provider_live"
    assert all(model.is_installed is False for model in by_id.values())
    serialized = settings_routes.ProviderModelsResponse(**response).model_dump()
    assert serialized["inventory_source"] == "mixed"
    assert serialized["workspace_inventory_verified"] is False
    assert serialized["models"][1]["source"] == "provider_live"


@pytest.mark.asyncio
async def test_nous_endpoint_override_is_denied_before_settings_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[str] = []
    monkeypatch.setattr(
        settings_routes, "get_settings_manager",
        lambda: SimpleNamespace(
            set_setting=lambda key, value, save=False: writes.append(key)
        ),
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(),
    )
    for url in (
        "https://untrusted.example/v1",
        "http://inference-api.nousresearch.com/v1",
        "https://inference-api.nousresearch.com/v1?token=leak",
    ):
        with pytest.raises(HTTPException) as exc:
            await settings_routes.update_model_settings(
                settings_routes.ModelSettingsUpdateRequest(
                    provider="nous",
                    base_url=url,
                ),
                current_user={"roles": ["admin"]},
            )
        assert exc.value.status_code in (400, 403)
    assert writes == []


@pytest.mark.asyncio
async def test_nous_discovery_rejects_previously_saved_untrusted_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        name="nous",
        enabled=True,
        endpoint=SimpleNamespace(
            base_url="https://inference-api.nousresearch.com/v1"
        ),
        provider_type=ProviderType.EXTERNAL,
        models=[],
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: provider),
    )
    monkeypatch.setattr(
        settings_routes, "_get_provider_override",
        lambda name: {"base_url": "https://untrusted.example/v1"},
    )
    with pytest.raises(HTTPException) as exc:
        await settings_routes.get_provider_models(
            "nous", current_user={"roles": ["admin"]}
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "outage", "credential_changed", "registration_aba"])
async def test_nous_model_discovery_uses_authorized_portal_endpoint_and_key(
    monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    from ai_karen_engine.core.model_runtime import provider_execution

    key = "credential-from-secret-manager"
    active_key = [key]
    provider = SimpleNamespace(
        name="nous",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://inference-api.nousresearch.com/v1"),
        provider_type=ProviderType.EXTERNAL,
        models=[
            SimpleNamespace(
                id="Hermes-4.3-36B", name="Hermes 4.3",
                family="hermes", capabilities={"text", "reasoning"},
            ),
            SimpleNamespace(
                id="Hermes-4-70B", name="Hermes 4",
                family="hermes", capabilities={"text"},
            ),
        ],
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(
            get_provider=lambda name: provider if name == "nous" else None,
            get_api_key=lambda name: active_key[0] if name == "nous" else None,
        ),
    )
    monkeypatch.setattr(settings_routes, "_get_provider_override", lambda name: {})

    async def no_local_models(*, runtime: str) -> list[object]:
        assert runtime == "nous"
        return []

    monkeypatch.setattr(
        settings_routes,
        "get_model_discovery_service",
        lambda: SimpleNamespace(get_models_async=no_local_models),
    )

    from dataclasses import replace
    from ai_karen_engine.core.model_runtime import provider_registry_service
    from ai_karen_engine.core.model_runtime.provider_endpoint import (
        ProviderEndpoint, ProviderEndpointType,
    )
    from ai_karen_engine.core.model_runtime.runtime_engine import EndpointKind
    from ai_karen_engine.core.model_runtime.provider_health_monitor import HealthStatus

    registry = provider_registry_service.ProviderRegistryService()
    endpoint = ProviderEndpoint(
        provider_id="nous", display_name="Nous",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url=provider.endpoint.base_url,
        kind=EndpointKind.CLOUD_PROVIDER, tenant_scoped=True,
    )
    registry.register_provider_endpoint(endpoint)
    monkeypatch.setattr(
        provider_registry_service, "get_provider_registry_service", lambda: registry,
    )

    def nous_inventory(base_url, *, api_key):
        assert base_url == provider.endpoint.base_url
        assert api_key == key
        if scenario == "outage":
            raise ConnectionError("unavailable")
        if scenario == "credential_changed":
            active_key[0] = "replacement-key"
        if scenario == "registration_aba":
            registry.register_provider_endpoint(replace(endpoint, default_model="other"))
            registry.register_provider_endpoint(endpoint)
        return ["Hermes-4.3-36B", "Hermes-4-405B"]

    monkeypatch.setattr(
        provider_execution, "discover_openai_compatible_model_ids", nous_inventory,
    )
    response = await settings_routes.get_provider_models(
        "nous", current_user={"roles": ["admin"]}
    )
    assert response["provider"] == "nous"
    assert response["workspace_inventory_verified"] is (scenario == "success")
    assert response["live_discovery_failed"] is (scenario != "success")
    by_id = {model.id: model for model in response["models"]}
    assert by_id["Hermes-4-70B"].source == "configured_catalog"
    if scenario == "success":
        assert response["discovery_status"] == "ready"
        assert response["inventory_source"] == "mixed"
        assert by_id["Hermes-4.3-36B"].source == "provider_live"
        assert by_id["Hermes-4-405B"].source == "provider_live"
    else:
        assert response["discovery_status"] == "catalog_only"
        assert all(model.source == "configured_catalog" for model in by_id.values())
    assert registry.health_monitor.get_provider_health("nous").health_status == HealthStatus.UNKNOWN

    assert key not in repr(response)

    with pytest.raises(HTTPException) as exc:
        await settings_routes.get_provider_models(
            "nous",
            base_url="http://127.0.0.1:11434/v1",
            current_user={"roles": ["admin"]},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_remote_outage_returns_honest_catalog_status_not_live_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.model_runtime import provider_execution

    provider = SimpleNamespace(
        name="gmi-cloud",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.gmi-serving.com/v1"),
        provider_type=ProviderType.REMOTE,
        models=[SimpleNamespace(id="saved-catalog", name="Saved catalog", family="cloud", capabilities=[])],
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(
            get_provider=lambda name: provider if name == "gmi-cloud" else None,
            get_api_key=lambda name: None,
        ),
    )
    monkeypatch.setattr(settings_routes, "_get_provider_override", lambda name: {})

    async def no_local_models(*, runtime: str) -> list[object]:
        return []

    monkeypatch.setattr(
        settings_routes, "get_model_discovery_service",
        lambda: SimpleNamespace(get_models_async=no_local_models),
    )

    def unreachable_provider(base_url, *, api_key):
        raise ConnectionError("provider unavailable")

    monkeypatch.setattr(provider_execution, "discover_openai_compatible_model_ids", unreachable_provider)
    response = await settings_routes.get_provider_models(
        "gmi-cloud", current_user={"roles": ["admin"]},
    )

    assert response["discovery_status"] == "catalog_only"
    assert response["inventory_source"] == "configured_catalog"
    assert response["live_discovery_failed"] is True
    assert [(item.id, item.source, item.is_installed) for item in response["models"]] == [
        ("saved-catalog", "configured_catalog", False),
    ]


@pytest.mark.asyncio
async def test_empty_ollama_inventory_serializes_with_timestamp(
    ollama_endpoint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(OllamaProvider, "get_models", lambda self: [])
    response = await settings_routes.get_provider_models(
        "ollama", current_user={"roles": ["admin"]},
    )
    serialized = settings_routes.ProviderModelsResponse(**response).model_dump()
    assert serialized["models"] == []
    assert serialized["discovery_status"] == "empty"
    assert serialized["inventory_source"] == "ollama_native"
    assert serialized["discovered_at"]


def test_discovery_response_contract_rejects_missing_timestamp() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        settings_routes.ProviderModelsResponse(
            provider="ollama", models=[], discovery_status="empty",
        )


@pytest.mark.asyncio
async def test_provider_validation_requires_real_candidate_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog discovery cannot substitute for an authenticated key probe."""
    from ai_karen_engine.config.provider_authentication import AuthenticationStatus
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
    )

    provider = SimpleNamespace(
        name="openai",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.openai.com/v1"),
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: provider if name == "openai" else None),
    )
    calls: list[tuple[str, str]] = []

    async def verify(provider_name: str, candidate: str):
        calls.append((provider_name, candidate))
        return SimpleNamespace(status=AuthenticationStatus.INVALID)

    monkeypatch.setattr(
        settings_routes,
        "get_provider_auth_manager",
        lambda: SimpleNamespace(validate_candidate_api_key=verify),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_model_discovery_service",
        lambda: pytest.fail("A model catalog is not credential verification"),
    )

    result = await settings_routes.validate_provider_settings(
        settings_routes.ProviderSettingsValidationRequest(
            provider="openai",
            api_key="invalid-secret-value",
            base_url="https://api.openai.com/v1",
        ),
        current_user={"roles": ["admin"]},
    )
    assert result["valid"] is False
    assert result["status"] == "invalid"
    assert result["models_discovered"] == 0
    assert calls == [("openai", "invalid-secret-value")]
    assert "invalid-secret-value" not in str(result)


@pytest.mark.asyncio
async def test_provider_validation_fails_closed_for_unapproved_endpoint_and_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
    )
    provider = SimpleNamespace(
        name="openai",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.openai.com/v1"),
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: provider),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_auth_manager",
        lambda: pytest.fail("Unapproved endpoint or missing key cannot trigger validation"),
    )
    for url in (
        "http://127.0.0.1:5432",
        "https://api.openai.com/v1?api_key=leak",
        "https://attacker.example/v1",
    ):
        result = await settings_routes.validate_provider_settings(
            settings_routes.ProviderSettingsValidationRequest(
                provider="openai", api_key="candidate", base_url=url
            ),
            current_user={"roles": ["admin"]},
        )
        assert result["valid"] is False
        assert result["status"] == "unverified"

    missing = await settings_routes.validate_provider_settings(
        settings_routes.ProviderSettingsValidationRequest(provider="openai"),
        current_user={"roles": ["admin"]},
    )
    assert missing["valid"] is False
    assert missing["status"] == "unverified"


@pytest.mark.asyncio
async def test_nous_candidate_key_never_probes_an_untrusted_saved_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
    )
    from ai_karen_engine.config.provider_authentication import (
        AuthenticationStatus,
        ProviderAuthenticationManager,
    )

    provider = SimpleNamespace(
        name="nous",
        enabled=True,
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
        endpoint=SimpleNamespace(base_url="https://untrusted.example/v1"),
    )
    manager = object.__new__(ProviderAuthenticationManager)
    manager.config_manager = SimpleNamespace(
        get_provider=lambda name: provider if name == "nous" else None,
    )

    async def forbidden_probe(*args, **kwargs):
        pytest.fail("Submitted token must not be sent to an untrusted host")

    monkeypatch.setattr(manager, "_validate_api_key_auth", forbidden_probe)
    result = await manager.validate_candidate_api_key(
        "nous", "sensitive-submitted-key"
    )
    assert result.status == AuthenticationStatus.UNKNOWN
    assert "sensitive-submitted-key" not in result.message


@pytest.mark.asyncio
async def test_provider_validation_rejects_consumer_before_any_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: pytest.fail("Consumer cannot inspect workspace credentials"),
    )
    with pytest.raises(HTTPException) as exc:
        await settings_routes.validate_provider_settings(
            settings_routes.ProviderSettingsValidationRequest(
                provider="openai", api_key="candidate"
            ),
            current_user={"roles": ["user"]},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_provider_validation_success_requires_authenticated_probe_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config.provider_authentication import AuthenticationStatus
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
    )

    provider = SimpleNamespace(
        name="openai",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.openai.com/v1"),
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
    )
    monkeypatch.setattr(
        settings_routes,
        "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: provider),
    )

    async def verified(provider_name: str, candidate: str):
        assert provider_name == "openai"
        assert candidate == "private-candidate"
        return SimpleNamespace(status=AuthenticationStatus.VALID)

    monkeypatch.setattr(
        settings_routes,
        "get_provider_auth_manager",
        lambda: SimpleNamespace(validate_candidate_api_key=verified),
    )
    result = await settings_routes.validate_provider_settings(
        settings_routes.ProviderSettingsValidationRequest(
            provider="openai", api_key="private-candidate"
        ),
        current_user={"roles": ["admin"]},
    )
    assert result["status"] == "verified"
    assert result["valid"] is True
    assert "private-candidate" not in str(result)


@pytest.mark.asyncio
async def test_provider_auth_manager_probes_candidate_without_persistence_or_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing auth adapter must use the submitted key, not a stored key."""
    import sys

    from ai_karen_engine.config.provider_authentication import (
        AuthenticationStatus,
        ProviderAuthenticationManager,
    )
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
        ProviderConfig,
        ProviderEndpoint,
    )

    config = ProviderConfig(
        name="openai",
        display_name="OpenAI",
        endpoint=ProviderEndpoint(base_url="https://api.openai.com/v1"),
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
    )
    manager = object.__new__(ProviderAuthenticationManager)
    manager.config_manager = SimpleNamespace(get_provider=lambda name: config)
    manager.validation_timeout = 2
    manager.get_api_key = lambda name: pytest.fail("Stored key must not be fetched")

    captured: list[tuple[str, dict[str, str], bool]] = []
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {"data": [{"id": "gpt-4o"}]}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, url, *, headers, allow_redirects):
            captured.append((url, headers, allow_redirects))
            return FakeResponse()

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(
            ClientTimeout=lambda **kwargs: kwargs,
            ClientSession=lambda **kwargs: FakeSession(),
        ),
    )
    result = await manager.validate_candidate_api_key("openai", "candidate-only")
    assert result.status == AuthenticationStatus.VALID
    assert captured == [(
        "https://api.openai.com/v1/models",
        {"User-Agent": "Kari-AI/1.0", "Authorization": "Bearer candidate-only"},
        False,
    )]
    assert manager.config_manager.get_provider("openai") is config


@pytest.mark.asyncio
async def test_candidate_validation_refuses_http_and_non_model_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ai_karen_engine.config.provider_authentication import (
        AuthenticationStatus,
        ProviderAuthenticationManager,
    )
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderAuthentication,
        ProviderConfig,
        ProviderEndpoint,
    )
    config = ProviderConfig(
        name="openai",
        display_name="OpenAI",
        endpoint=ProviderEndpoint(base_url="http://api.openai.com/v1"),
        authentication=ProviderAuthentication(type=AuthenticationType.API_KEY),
    )
    manager = object.__new__(ProviderAuthenticationManager)
    manager.config_manager = SimpleNamespace(get_provider=lambda name: config)
    manager.validation_timeout = 2
    blocked = await manager.validate_candidate_api_key("openai", "private-candidate")
    assert blocked.status == AuthenticationStatus.UNKNOWN

    config.endpoint.base_url = "https://api.openai.com/v1"

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {"ok": True}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(
            ClientTimeout=lambda **kwargs: kwargs,
            ClientSession=lambda **kwargs: FakeSession(),
        ),
    )
    unknown = await manager.validate_candidate_api_key("openai", "private-candidate")
    assert unknown.status == AuthenticationStatus.UNKNOWN
    assert "private-candidate" not in unknown.message

def test_zai_admin_enablement_and_chat_visibility_survive_provider_restart(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config.llm_provider_config import LLMProviderConfigManager

    monkeypatch.delenv("ZAI_ENABLED", raising=False)
    monkeypatch.delenv("KARI_ZAI_ENABLED", raising=False)
    first = LLMProviderConfigManager(config_dir=tmp_path)
    assert first.get_provider("zai").enabled is False

    enabled = first.set_chat_controls("zai", provider_enabled=True, chat_enabled=True)
    assert enabled.enabled is True
    assert first.set_chat_controls(
        "zai", model_id="glm-4.5", model_enabled=False
    ).chat_model_visibility["glm-4.5"] is False

    restarted = LLMProviderConfigManager(config_dir=tmp_path)
    config = restarted.get_provider("zai")
    assert config.enabled is True
    assert config.chat_enabled is True
    assert config.chat_model_visibility["glm-4.5"] is False
    restarted.set_chat_controls("zai", model_id="glm-4.5", model_enabled=True)
    assert "glm-4.5" not in restarted.get_provider("zai").chat_model_visibility


def test_admin_cannot_override_explicit_environment_disable(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.config.llm_provider_config import LLMProviderConfigManager

    monkeypatch.setenv("KARI_ZAI_ENABLED", "false")
    manager = LLMProviderConfigManager(config_dir=tmp_path)
    with pytest.raises(ValueError, match="environment"):
        manager.set_chat_controls("zai", provider_enabled=True)
    with pytest.raises(ValueError, match="Built-in"):
        manager.set_chat_controls("builtin_transformers", chat_enabled=False)
    with pytest.raises(ValueError, match="Model ID"):
        manager.set_chat_controls("zai", model_id="not-a-model", model_enabled=None)


@pytest.mark.asyncio
async def test_admin_chat_visibility_endpoint_has_audited_backend_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = SimpleNamespace(
        name="zai", enabled=False, chat_enabled=True, chat_model_visibility={},
        provider_type=ProviderType.EXTERNAL, models=[SimpleNamespace(id="glm-4.5")],
    )
    writes = []
    audit = []

    def save(name, **kwargs):
        assert name == "zai"
        writes.append(kwargs)
        current.enabled = kwargs["provider_enabled"]
        current.chat_enabled = kwargs["chat_enabled"]
        return current

    manager = SimpleNamespace(
        get_provider=lambda name: current if name == "zai" else None,
        set_chat_controls=save,
    )
    monkeypatch.setattr(settings_routes, "get_provider_config_manager", lambda: manager)
    monkeypatch.setattr(settings_routes, "AdminProviderService", lambda: SimpleNamespace(
        _audit_mutation=lambda **kwargs: audit.append(kwargs)
    ))
    monkeypatch.setattr(settings_routes, "get_registry", lambda: SimpleNamespace(
        invalidate_provider_cache=lambda provider: None
    ))
    async def confirmed():
        return {"providers": [{"id": "zai", "enabled": current.enabled, "chat_enabled": current.chat_enabled}]}

    monkeypatch.setattr(settings_routes, "build_model_settings_payload", confirmed)
    result = await settings_routes.update_provider_chat_access(
        "zai",
        settings_routes.ProviderChatAccessRequest(provider_enabled=True, chat_enabled=False),
        current_user={"user_id": "administrator", "roles": ["admin"]},
    )
    assert result["providers"][0]["enabled"] is True
    assert result["providers"][0]["chat_enabled"] is False
    assert writes[0]["provider_enabled"] is True
    assert audit[0]["operator_id"] == "administrator"

    async def no_unlisted_models(*_args, **_kwargs):
        return {"models": []}

    monkeypatch.setattr(settings_routes, "get_provider_models", no_unlisted_models)
    with pytest.raises(HTTPException) as exc:
        await settings_routes.update_provider_chat_access(
            "zai",
            settings_routes.ProviderChatAccessRequest(
                model_id="injected-unlisted-model", model_enabled=True
            ),
            current_user={"user_id": "administrator", "roles": ["admin"]},
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_consumer_model_key_rejects_unverified_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog success and nonempty keys never authorize personal key storage."""
    import uuid
    from unittest.mock import AsyncMock
    from pydantic import SecretStr

    tenant = uuid.uuid4()
    provider_id = uuid.uuid4()
    provider = SimpleNamespace(
        name="openai", enabled=True, chat_enabled=True,
        provider_type=ProviderType.EXTERNAL,
        authentication=SimpleNamespace(type=settings_routes.AuthenticationType.API_KEY),
    )
    vault = SimpleNamespace(
        get_provider=AsyncMock(return_value=SimpleNamespace(
            id=provider_id, provider_id="openai", enabled=True,
            is_system=True, provider_type="api_key",
            config={"managed_for": "model_api_key"},
        )),
        create_owned_credential=AsyncMock(),
    )
    auth = SimpleNamespace(validate_candidate_api_key=AsyncMock(
        return_value=SimpleNamespace(status=settings_routes.AuthenticationStatus.INVALID)
    ))
    monkeypatch.setattr(settings_routes, "get_provider_config_manager", lambda: SimpleNamespace(
        get_provider=lambda name: provider if name == "openai" else None
    ))
    monkeypatch.setattr(settings_routes, "get_credential_vault_service", lambda: vault)
    monkeypatch.setattr(settings_routes, "get_provider_auth_manager", lambda: auth)
    actor = {"tenant_id": str(tenant), "user_id": "alice", "roles": ["user"]}
    payload = settings_routes.ConsumerModelKeyCreate(
        provider="openai", api_key=SecretStr("consumer-test-candidate")
    )
    with pytest.raises(HTTPException) as denied:
        await settings_routes.create_consumer_model_key(payload, current_user=actor)
    assert denied.value.status_code == 422
    vault.create_owned_credential.assert_not_awaited()

    auth.validate_candidate_api_key.return_value.status = (
        settings_routes.AuthenticationStatus.VALID
    )
    vault.create_owned_credential.return_value = SimpleNamespace(
        id=uuid.uuid4(), status="active", masked_hint="••••date",
    )
    created = await settings_routes.create_consumer_model_key(
        payload, current_user=actor
    )
    assert created.provider == "openai"
    assert created.runtime_authorized is False
    assert "consumer-test-candidate" not in created.model_dump_json()
    vault.create_owned_credential.assert_awaited_once()
    args = vault.create_owned_credential.await_args.args
    assert args[0].credential_type == "model_api_key"
    assert args[1][0].encrypted_value == "consumer-test-candidate"
    assert args[2:] == (tenant, "alice")
    auth.validate_candidate_api_key.assert_awaited_with(
        "openai", "consumer-test-candidate"
    )


@pytest.mark.asyncio
async def test_consumer_model_key_scopes_read_revoke_delete_to_authenticated_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from unittest.mock import AsyncMock

    tenant = uuid.uuid4()
    credential_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    vault = SimpleNamespace(
        list_owned_credentials=AsyncMock(return_value=[
            SimpleNamespace(
                id=credential_id, provider_id=provider_id, status="active",
                masked_hint="••••test", secrets=["must-never-serialize"],
            ),
        ]),
        list_providers=AsyncMock(return_value=[
            SimpleNamespace(id=provider_id, provider_id="openai")
        ]),
        revoke_owned_credential=AsyncMock(return_value=True),
        delete_owned_credential=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(settings_routes, "get_credential_vault_service", lambda: vault)
    actor = {"tenant_id": str(tenant), "user_id": "alice", "roles": ["user"]}
    listed = await settings_routes.list_consumer_model_keys(
        limit=10, offset=0, current_user=actor
    )
    assert len(listed.credentials) == 1
    assert listed.credentials[0].provider == "openai"
    assert listed.credentials[0].runtime_authorized is False
    assert "must-never-serialize" not in listed.model_dump_json()
    vault.list_owned_credentials.assert_awaited_with(
        tenant, "alice", limit=10, offset=0
    )

    assert await settings_routes.revoke_consumer_model_key(
        credential_id, current_user=actor
    ) == {"locally_revoked": True, "provider_revocation_verified": False}
    vault.revoke_owned_credential.assert_awaited_with(
        credential_id, tenant, "alice", reason="consumer_request"
    )
    with pytest.raises(HTTPException) as blocked:
        await settings_routes.delete_consumer_model_key(
            credential_id, current_user=actor
        )
    assert blocked.value.status_code == 409
    vault.delete_owned_credential.assert_awaited_with(
        credential_id, tenant, "alice"
    )


@pytest.mark.asyncio
async def test_consumer_model_key_denies_invalid_identity_and_unapproved_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from unittest.mock import AsyncMock
    from pydantic import SecretStr

    tenant = uuid.uuid4()
    vault = SimpleNamespace(
        get_provider=AsyncMock(),
        create_owned_credential=AsyncMock(),
    )
    monkeypatch.setattr(settings_routes, "get_credential_vault_service", lambda: vault)
    payload = settings_routes.ConsumerModelKeyCreate(
        provider="openai", api_key=SecretStr("bounded-test-key")
    )
    for identity in (
        {"tenant_id": "default", "user_id": "alice"},
        {"tenant_id": str(tenant), "user_id": ""},
        {"tenant_id": str(tenant), "user_id": "alice "},
        {"tenant_id": "", "user_id": "alice"},
    ):
        with pytest.raises(HTTPException) as denied:
            await settings_routes.create_consumer_model_key(
                payload, current_user=identity
            )
        assert denied.value.status_code == 403

    # Even a configured custom vendor cannot receive a key from this endpoint.
    unapproved = SimpleNamespace(
        name="custom", enabled=True, chat_enabled=True,
        provider_type=ProviderType.CUSTOM,
        authentication=SimpleNamespace(type=settings_routes.AuthenticationType.API_KEY),
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda _: unapproved),
    )
    with pytest.raises(HTTPException) as denied:
        await settings_routes.create_consumer_model_key(
            settings_routes.ConsumerModelKeyCreate(
                provider="custom", api_key=SecretStr("candidate-test-key")
            ),
            current_user={"tenant_id": str(tenant), "user_id": "alice"},
        )
    assert denied.value.status_code == 403
    vault.get_provider.assert_not_awaited()
    vault.create_owned_credential.assert_not_awaited()

    with pytest.raises(HTTPException) as denied:
        await settings_routes.create_consumer_model_key(
            settings_routes.ConsumerModelKeyCreate(
                provider="openai", api_key=SecretStr("contains\nnewline")
            ),
            current_user={"tenant_id": str(tenant), "user_id": "alice"},
        )
    assert denied.value.status_code == 422


@pytest.mark.asyncio
async def test_admin_personal_model_key_provisioning_is_tenant_scoped_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from unittest.mock import AsyncMock

    tenant = uuid.uuid4()
    provider_uuid = uuid.uuid4()
    registry = SimpleNamespace(
        name="openai", display_name="OpenAI", enabled=True, chat_enabled=True,
        provider_type=ProviderType.EXTERNAL,
        authentication=SimpleNamespace(type=settings_routes.AuthenticationType.API_KEY),
    )
    created = SimpleNamespace(
        id=provider_uuid, tenant_id=tenant, provider_id="openai",
        enabled=True, is_system=True, provider_type="api_key",
        config={"managed_for": "model_api_key"},
    )
    vault = SimpleNamespace(
        get_provider=AsyncMock(return_value=None),
        create_provider=AsyncMock(return_value=created),
    )
    monkeypatch.setattr(settings_routes, "get_credential_vault_service", lambda: vault)
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: registry if name == "openai" else None),
    )
    actor = {"tenant_id": str(tenant), "user_id": "administrator", "roles": ["admin"]}
    result = await settings_routes.provision_consumer_model_key_provider(
        "openai", current_user=actor
    )
    assert result.provider == "openai"
    assert result.storage_enabled is True
    assert result.runtime_authorized is False
    vault.get_provider.assert_awaited_once_with("openai", tenant)
    vault.create_provider.assert_awaited_once()
    args = vault.create_provider.await_args.args
    assert args[0].provider_id == "openai"
    assert args[0].config == {"managed_for": "model_api_key"}
    assert args[0].is_system is True
    assert args[0].provider_type.value == "api_key"
    assert args[1:] == (tenant, "administrator")

    vault.get_provider.return_value = created
    again = await settings_routes.provision_consumer_model_key_provider(
        "openai", current_user=actor
    )
    assert again.storage_enabled is True
    vault.create_provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_key_provisioning_denies_collisions_and_unapproved_vendors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from unittest.mock import AsyncMock

    tenant = uuid.uuid4()
    actor = {"tenant_id": str(tenant), "user_id": "admin"}
    registry = SimpleNamespace(
        name="openai", display_name="OpenAI", enabled=True, chat_enabled=True,
        provider_type=ProviderType.EXTERNAL,
        authentication=SimpleNamespace(type=settings_routes.AuthenticationType.API_KEY),
    )
    vault = SimpleNamespace(
        get_provider=AsyncMock(return_value=SimpleNamespace(
            provider_id="openai", enabled=True, is_system=True,
            provider_type="api_key", config={"managed_for": "plugin_credentials"},
        )),
        create_provider=AsyncMock(),
        create_owned_credential=AsyncMock(),
    )
    monkeypatch.setattr(settings_routes, "get_credential_vault_service", lambda: vault)
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda name: registry if name == "openai" else None),
    )
    with pytest.raises(HTTPException) as exc:
        await settings_routes.provision_consumer_model_key_provider(
            "openai", current_user=actor
        )
    assert exc.value.status_code == 409
    vault.create_provider.assert_not_awaited()

    from pydantic import SecretStr
    with pytest.raises(HTTPException) as exc:
        await settings_routes.create_consumer_model_key(
            settings_routes.ConsumerModelKeyCreate(
                provider="openai", api_key=SecretStr("private-test-key")
            ), current_user=actor,
        )
    assert exc.value.status_code == 409
    vault.create_owned_credential.assert_not_awaited()

    with pytest.raises(HTTPException) as exc:
        await settings_routes.provision_consumer_model_key_provider(
            "custom", current_user=actor
        )
    assert exc.value.status_code == 403
    vault.create_provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_governed_vendor_rejects_unapproved_saved_endpoint_before_key_read(monkeypatch):
    from ai_karen_engine.core.model_runtime import provider_execution

    provider = SimpleNamespace(
        name="gmi-cloud", enabled=True,
        endpoint=SimpleNamespace(base_url="https://api.gmi-serving.com/v1"),
        provider_type=ProviderType.EXTERNAL, models=[],
    )
    monkeypatch.setattr(
        settings_routes, "get_provider_config_manager",
        lambda: SimpleNamespace(
            get_provider=lambda name: provider,
            get_api_key=lambda name: pytest.fail("key must not be read for a foreign URL"),
        ),
    )
    monkeypatch.setattr(
        settings_routes, "_get_provider_override",
        lambda name: {"base_url": "https://foreign.example.invalid/v1"},
    )
    monkeypatch.setattr(
        provider_execution, "discover_openai_compatible_model_ids",
        lambda *args, **kwargs: pytest.fail("foreign endpoint must not be contacted"),
    )
    with pytest.raises(HTTPException) as exc:
        await settings_routes.get_provider_models(
            "gmi-cloud", current_user={"roles": ["admin"]},
        )
    assert exc.value.status_code == 403
