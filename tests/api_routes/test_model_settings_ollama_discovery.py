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
    from ai_karen_engine.integrations.providers import openai_compatible_provider

    provider = SimpleNamespace(
        name="gmi-cloud",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://models.example.invalid/v1"),
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

    class RemoteCatalog:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["base_url"] == "https://models.example.invalid/v1"

        def get_models(self) -> list[str]:
            return ["live-model", "new-live-model"]

    monkeypatch.setattr(openai_compatible_provider, "OpenAICompatibleProvider", RemoteCatalog)
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
    assert serialized["models"][1]["source"] == "provider_live"


@pytest.mark.asyncio
async def test_remote_outage_returns_honest_catalog_status_not_live_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.integrations.providers import openai_compatible_provider

    provider = SimpleNamespace(
        name="gmi-cloud",
        enabled=True,
        endpoint=SimpleNamespace(base_url="https://models.example.invalid/v1"),
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

    class UnreachableProvider:
        def __init__(self, **kwargs: object) -> None:
            pass

        def get_models(self) -> list[str]:
            raise ConnectionError("provider unavailable")

    monkeypatch.setattr(openai_compatible_provider, "OpenAICompatibleProvider", UnreachableProvider)
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
