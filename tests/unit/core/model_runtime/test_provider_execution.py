from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ai_karen_engine.core.model_runtime.provider_execution import (
    get_provider_execution_registry,
    register_provider_factory,
)


@dataclass
class _FakeProvider:
    model: str | None = None


@pytest.fixture(autouse=True)
def _reset_execution_registry():
    registry = get_provider_execution_registry()
    registry.clear_factory()
    yield
    registry.clear_factory()


def test_unconfigured_registry_fails_closed() -> None:
    registry = get_provider_execution_registry()

    assert registry.is_configured() is False
    assert registry.create_provider("local") is None


def test_registered_factory_receives_provider_and_options() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def factory(provider_id: str, **kwargs: Any) -> _FakeProvider:
        calls.append((provider_id, kwargs))
        return _FakeProvider(model=kwargs.get("model"))

    register_provider_factory(factory)
    provider = get_provider_execution_registry().create_provider(
        "lmstudio",
        model="local-model",
        base_url="http://127.0.0.1:1234/v1",
    )

    assert provider is not None
    assert provider.model == "local-model"
    assert calls == [
        (
            "lmstudio",
            {
                "model": "local-model",
                "base_url": "http://127.0.0.1:1234/v1",
            },
        )
    ]


def test_identical_factory_registration_is_idempotent() -> None:
    def factory(provider_id: str, **kwargs: Any) -> _FakeProvider:
        return _FakeProvider(model=kwargs.get("model"))

    register_provider_factory(factory)
    register_provider_factory(factory)

    assert get_provider_execution_registry().is_configured() is True


def test_different_factory_cannot_silently_replace_authority() -> None:
    def first(provider_id: str, **kwargs: Any) -> _FakeProvider:
        return _FakeProvider(model="first")

    def second(provider_id: str, **kwargs: Any) -> _FakeProvider:
        return _FakeProvider(model="second")

    register_provider_factory(first)

    with pytest.raises(RuntimeError, match="already registered"):
        register_provider_factory(second)

    provider = get_provider_execution_registry().create_provider("local")
    assert provider is not None
    assert provider.model == "first"


def test_controlled_bootstrap_can_replace_factory_explicitly() -> None:
    def first(provider_id: str, **kwargs: Any) -> _FakeProvider:
        return _FakeProvider(model="first")

    def second(provider_id: str, **kwargs: Any) -> _FakeProvider:
        return _FakeProvider(model="second")

    register_provider_factory(first)
    register_provider_factory(second, replace=True)

    provider = get_provider_execution_registry().create_provider("local")
    assert provider is not None
    assert provider.model == "second"
