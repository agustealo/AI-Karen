"""KCHAT-AUTH-05B2B2B: startup registration is never model execution."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from ai_karen_engine.llm_orchestrator import LLMOrchestrator, ModelStatus


class _ForbiddenInferenceProvider:
    """An actual warm/generate/embed invocation must fail this test."""

    def __init__(self) -> None:
        self.called: list[str] = []

    def warm_cache(self) -> None:
        self.called.append("warm_cache")
        raise AssertionError("unauthorized warm_cache")

    def generate_text(self, *args: object, **kwargs: object) -> str:
        self.called.append("generate_text")
        raise AssertionError("unauthorized generate_text")

    def embed(self, *args: object, **kwargs: object) -> list[float]:
        self.called.append("embed")
        raise AssertionError("unauthorized embed")


class _RegisteredModels:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, SimpleNamespace] = {}

    def register(
        self,
        model_id: str,
        provider: object,
        capabilities: list[str],
        **kwargs: object,
    ) -> None:
        with self._lock:
            if model_id in self._models:
                raise ValueError("duplicate model")
            self._models[model_id] = SimpleNamespace(
                model=provider,
                capabilities=list(capabilities),
                status=ModelStatus.ACTIVE,
                warmed=False,
                latencies=[],
                tags=list(kwargs.get("tags") or []),
                weight=kwargs.get("weight", 1),
            )


@pytest.mark.parametrize("provider_name", ["local", "remote"])
def test_opt_in_preload_only_registers_and_never_calls_model(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
) -> None:
    import ai_karen_engine.integrations.provider_registry as provider_registry

    provider = _ForbiddenInferenceProvider()
    models = [
        SimpleNamespace(name="first", capabilities=["generic"]),
        SimpleNamespace(name="second", capabilities=["generic"]),
    ]

    class _Discovery:
        def list_providers(self) -> list[str]:
            return [provider_name]

        def get_provider_info(self, name: str) -> SimpleNamespace:
            assert name == provider_name
            return SimpleNamespace(models=models, default_model="first")

        def get_provider(self, name: str, *, model: str) -> object:
            assert (name, model) == (provider_name, "first")
            return provider

    monkeypatch.setattr(provider_registry, "get_provider_registry", _Discovery)
    monkeypatch.setenv("KARI_ENABLE_PROVIDER_PRELOAD", "true")
    monkeypatch.setenv("KARI_WARM_CLOUD_PROVIDERS", "true")

    orchestrator = object.__new__(LLMOrchestrator)
    orchestrator.registry = _RegisteredModels()
    monkeypatch.setattr(orchestrator, "_register_local_models", lambda: None)
    monkeypatch.setattr(orchestrator, "_ensure_fallback_provider", lambda: None)

    orchestrator._preload_providers()

    registered = orchestrator.registry._models
    assert list(registered) == [f"{provider_name}:first"]
    assert registered[f"{provider_name}:first"].warmed is False
    assert registered[f"{provider_name}:first"].latencies == []
    assert provider.called == []


def test_fallback_registration_does_not_synthesize_unauthenticated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_karen_engine.integrations.providers.fallback_provider as fallback_module

    class _Fallback(_ForbiddenInferenceProvider):
        model = "guarded-fallback"

    registered = _RegisteredModels()
    orchestrator = object.__new__(LLMOrchestrator)
    orchestrator.registry = registered
    monkeypatch.setattr(fallback_module, "FallbackProvider", _Fallback)

    orchestrator._ensure_fallback_provider()
    fallback = registered._models["fallback:guarded-fallback"]
    assert fallback.warmed is False
    assert fallback.latencies == []
    assert fallback.model.called == []

    # Refresh of the same fallback is bookkeeping, not another model call.
    orchestrator._ensure_fallback_provider()
    refreshed = registered._models["fallback:guarded-fallback"]
    assert refreshed.warmed is False
    assert refreshed.model.called == []


def test_actual_observed_latency_can_still_mark_a_registered_model_warm() -> None:
    orchestrator = object.__new__(LLMOrchestrator)
    orchestrator.registry = _RegisteredModels()
    provider = _ForbiddenInferenceProvider()
    orchestrator.registry.register("local:observed", provider, ["generic"])
    entry = orchestrator.registry._models["local:observed"]
    entry.record_latency = entry.latencies.append

    assert entry.warmed is False
    orchestrator._track_latency("local:observed", 0.125)
    assert entry.warmed is True
    assert entry.latencies == [0.125]
    assert provider.called == []
