"""Application model settings are consumed only by the canonical ChatRuntime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.model_runtime import provider_registry_service
from ai_karen_engine.services.formatting import settings_manager


def _request(
    provider: str | None = None, model: str | None = None,
) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1",
        ),
        preferred_provider=provider,
        preferred_model=model,
    )


def _settings(values: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(get_setting=lambda name: values.get(name))


def test_admin_saved_provider_and_model_become_runtime_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_manager, "get_settings_manager",
        lambda: _settings({
            "provider": "ollama",
            "model": "smollm2:135m",
            "model_providers.ollama.last_model": "smollm2:135m",
        }),
    )
    registry = SimpleNamespace(
        canonicalize_provider_id=lambda value: "ollama-local" if value == "ollama" else value,
        get_provider_endpoint=lambda value: SimpleNamespace(enabled=True) if value == "ollama-local" else None,
    )
    monkeypatch.setattr(
        provider_registry_service, "get_provider_registry_service", lambda: registry,
    )

    request = _request()
    ChatRuntime._apply_selected_model_settings(request)
    assert request.preferred_provider == "ollama-local"
    assert request.preferred_model == "smollm2:135m"
    assert request.metadata["model_selection_source"] == "application_settings"


@pytest.mark.parametrize(
    ("explicit_provider", "explicit_model"),
    [("lmstudio-desktop", "a-model"), ("ollama-local", None), (None, "manual-model")],
)
def test_explicit_chat_selection_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
    explicit_provider: str | None,
    explicit_model: str | None,
) -> None:
    monkeypatch.setattr(
        settings_manager, "get_settings_manager",
        lambda: pytest.fail("Explicit request must not read saved global defaults"),
    )
    request = _request(explicit_provider, explicit_model)
    ChatRuntime._apply_selected_model_settings(request)
    assert request.preferred_provider == explicit_provider
    assert request.preferred_model == explicit_model


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "local_gguf", "model": "legacy.gguf"},
        {"provider": "ollama", "model": "auto", "model_providers.ollama.last_model": "auto"},
        {"provider": "ollama", "model": "new-model", "model_providers.ollama.last_model": "old-model"},
    ],
)
def test_unverified_or_legacy_model_defaults_are_not_forced(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
) -> None:
    monkeypatch.setattr(
        settings_manager, "get_settings_manager", lambda: _settings(values),
    )
    monkeypatch.setattr(
        provider_registry_service, "get_provider_registry_service",
        lambda: pytest.fail("Unverified settings must not resolve runtime endpoints"),
    )
    request = _request()
    ChatRuntime._apply_selected_model_settings(request)
    assert request.preferred_provider is None
    assert request.preferred_model is None


def test_disabled_provider_cannot_be_forced_by_saved_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_manager, "get_settings_manager",
        lambda: _settings({
            "provider": "ollama",
            "model": "smollm2:135m",
            "model_providers.ollama.last_model": "smollm2:135m",
        }),
    )
    monkeypatch.setattr(
        provider_registry_service, "get_provider_registry_service",
        lambda: SimpleNamespace(
            canonicalize_provider_id=lambda name: "ollama-local",
            get_provider_endpoint=lambda name: SimpleNamespace(enabled=False),
        ),
    )
    request = _request()
    ChatRuntime._apply_selected_model_settings(request)
    assert request.preferred_provider is None
    assert request.preferred_model is None
