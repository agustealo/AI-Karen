"""Tests for ProviderRegistryService endpoint capabilities."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"
CORE_MODEL_RUNTIME = SRC / "core" / "model_runtime"


def _load_module(name: str, path: pathlib.Path):
    """Load a module in isolation, mocking heavy dependencies."""
    numpy_mock = types.ModuleType("numpy")
    sys.modules.setdefault("numpy", numpy_mock)

    pkg_name = "ai_karen_engine.core.model_runtime"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(CORE_MODEL_RUNTIME)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    for parent in [
        "ai_karen_engine.core",
        "ai_karen_engine",
    ]:
        if parent not in sys.modules:
            mod = types.ModuleType(parent)
            mod.__path__ = []
            mod.__package__ = parent
            sys.modules[parent] = mod

    # Mock core.logging to avoid deep import chain
    logging_pkg = "ai_karen_engine.core.logging"
    if logging_pkg not in sys.modules:
        logging_mod = types.ModuleType(logging_pkg)
        logging_mod.get_logger = lambda name: __import__("logging").getLogger(name)
        logging_mod.__package__ = logging_pkg
        sys.modules[logging_pkg] = logging_mod

    # Mock provider_health_monitor to avoid import chain
    phm_pkg = "ai_karen_engine.core.model_runtime.provider_health_monitor"
    if phm_pkg not in sys.modules:
        phm_mod = types.ModuleType(phm_pkg)
        phm_mod.__package__ = phm_pkg

        from enum import Enum as EnumType
        class HealthStatus(str, EnumType):
            HEALTHY = "healthy"
            DEGRADED = "degraded"
            UNHEALTHY = "unhealthy"
            UNAVAILABLE = "unavailable"
            UNKNOWN = "unknown"

        class ProviderHealthMonitor:
            def __init__(self, registry=None, check_interval=300, cache_ttl=300):
                self._registry = registry
                self.check_interval = check_interval
                self._cache_ttl = cache_ttl
                self._health_cache = {}
                self._prev_statuses = {}

            def invalidate_provider(self, provider_id):
                self._health_cache.pop(provider_id, None)
                self._prev_statuses.pop(provider_id, None)

            def get_all_provider_names(self):
                return []

            def get_provider_health(self, provider_id):
                # Isolated test doubles must implement the canonical monitor
                # interface rather than force the registry to fabricate health.
                return types.SimpleNamespace(health_status=HealthStatus.UNKNOWN)

        phm_mod.HealthStatus = HealthStatus
        phm_mod.ProviderHealthMonitor = ProviderHealthMonitor
        sys.modules[phm_pkg] = phm_mod

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def provider_registry_service_module():
    path = CORE_MODEL_RUNTIME / "provider_registry_service.py"
    return _load_module("provider_registry_service_isolated", path)


class TestProviderRegistryServiceEndpoints:
    def test_default_local_endpoints_registered(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        assert "lmstudio-desktop" in registry._provider_endpoints
        assert "ollama-local" in registry._provider_endpoints
        assert "llamacpp-server" in registry._provider_endpoints

    def test_lmstudio_endpoint_metadata(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        endpoint = registry.get_provider_endpoint("lmstudio-desktop")
        assert endpoint is not None
        assert endpoint.base_url == "http://localhost:1234/v1"
        assert endpoint.supports_streaming is True
        assert "tools" in endpoint.capabilities
        assert "structured_output" in endpoint.capabilities

    def test_ollama_endpoint_metadata(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        endpoint = registry.get_provider_endpoint("ollama-local")
        assert endpoint is not None
        assert endpoint.base_url == "http://localhost:11434/v1"
        assert {"chat_completion", "text_generation"}.issubset(
            registry.effective_endpoint_capabilities(endpoint)
        )

    def test_resolve_capable_targets(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        targets = registry.resolve_capable_targets(
            required_capabilities={"chat"},
            healthy_only=False,
        )
        target_ids = [t.provider_id for t in targets]
        assert "lmstudio-desktop" in target_ids

        targets = registry.resolve_capable_targets(
            required_capabilities={"chat_completion", "text_generation"},
            healthy_only=False,
        )
        target_ids = [t.provider_id for t in targets]
        assert "ollama-local" in target_ids

    def test_select_best_target_preferred(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        target = registry.select_best_target(
            required_capabilities={"chat"},
            preferred_target_id="lmstudio-desktop",
            healthy_only=False,
        )
        assert target is not None
        assert target.provider_id == "lmstudio-desktop"

    def test_fallback_chains_updated(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
        registry = ProviderRegistryService()

        chain = registry._fallback_chains.get("text_generation")
        assert chain is not None
        assert "builtin_transformers" not in chain.fallbacks
        assert "lmstudio-desktop" in chain.fallbacks

        chain = registry._fallback_chains.get("local_first")
        assert chain is not None
        assert chain.primary == "lmstudio-desktop"

    def test_canonical_aliases_updated(self, provider_registry_service_module):
        ProviderRegistryService = provider_registry_service_module.ProviderRegistryService

        assert ProviderRegistryService.CANONICAL_PROVIDER_ALIASES["lm_studio"] == "lmstudio-desktop"
        assert ProviderRegistryService.CANONICAL_PROVIDER_ALIASES["ollama"] == "ollama-local"
        assert ProviderRegistryService.CANONICAL_PROVIDER_ALIASES["llama_cpp"] == "llamacpp-server"

    def test_expression_chat_capability_normalization(self, provider_registry_service_module):
        """Built-in chat and configured OpenAI-compatible declarations agree."""
        Registry = provider_registry_service_module.ProviderRegistryService
        registry = Registry()
        needed = {"chat_completion", "text_generation"}
        targets = registry.resolve_capable_targets(
            required_capabilities=needed, healthy_only=False,
        )
        ids = {endpoint.provider_id for endpoint in targets}
        assert {"ollama-local", "lmstudio-desktop", "llamacpp-server"}.issubset(ids)

        for provider_id in ("ollama-local", "lmstudio-desktop", "llamacpp-server"):
            status = registry.get_provider_status(provider_id)
            assert status is not None
            assert provider_registry_service_module.ProviderCapability.CHAT_COMPLETION in status.capabilities
            assert provider_registry_service_module.ProviderCapability.TEXT_GENERATION in status.capabilities
            selected = registry.select_best_target(
                required_capabilities=needed,
                preferred_target_id=provider_id,
                healthy_only=False,
            )
            assert selected is not None
            assert selected.provider_id == provider_id

        configured = registry.register_openai_compatible_endpoint(
            "compatible-chat-test", "Compatible Chat Test",
            base_url="http://localhost:5000/v1",
        )
        assert "chat" in registry.effective_endpoint_capabilities(configured)
        assert needed.issubset(registry.effective_endpoint_capabilities(configured))

    def test_text_only_endpoint_cannot_claim_chat_authority(self, provider_registry_service_module):
        Registry = provider_registry_service_module.ProviderRegistryService
        registry = Registry()
        text_only = registry.register_openai_compatible_endpoint(
            "text-only-test", "Text Only Test",
            base_url="http://localhost:5001/v1",
            capabilities=["text_generation"],
        )
        assert "chat" not in registry.effective_endpoint_capabilities(text_only)
        assert "chat_completion" not in registry.effective_endpoint_capabilities(text_only)
        selected = registry.select_best_target(
            required_capabilities={"chat_completion", "text_generation"},
            preferred_target_id="text-only-test",
            healthy_only=False,
        )
        assert selected is None or selected.provider_id != "text-only-test"


@pytest.fixture
def personal_provider_without_workspace_key(monkeypatch):
    """A registered vendor with no workspace API key still has trusted config."""
    from types import SimpleNamespace

    configured = {"workspace_key": False}
    endpoint = SimpleNamespace(
        base_url="https://api.openai.com/v1",
        timeout=30,
        models_endpoint=True,
    )
    settings = SimpleNamespace(
        enabled=True,
        provider_type="external",
        authentication=SimpleNamespace(
            type="api_key", api_key_env_var="OPENAI_API_KEY",
        ),
        endpoint=endpoint,
        capabilities=("streaming",),
        default_model="registered-model",
        display_name="Registered OpenAI",
        priority=80,
    )
    manager = SimpleNamespace(
        get_provider=lambda provider: settings if provider == "openai" else None,
        is_provider_configured=lambda provider: (
            provider == "openai" and configured["workspace_key"]
        ),
    )
    fake = types.ModuleType("ai_karen_engine.config.llm_provider_config")
    fake.OPENAI_COMPATIBLE_PROVIDER_DEFAULTS = {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
    }
    fake.AuthenticationType = SimpleNamespace(API_KEY="api_key")
    fake.ProviderType = SimpleNamespace(EXTERNAL="external")
    fake.get_provider_config_manager = lambda: manager
    monkeypatch.setitem(
        sys.modules, "ai_karen_engine.config.llm_provider_config", fake
    )
    return configured, settings


def test_personal_vendor_projection_does_not_claim_workspace_availability(
    provider_registry_service_module, personal_provider_without_workspace_key
):
    configured, _ = personal_provider_without_workspace_key
    registry = provider_registry_service_module.ProviderRegistryService()

    # General chat remains unconfigured; no secret-free cloud fallback.
    assert registry.get_provider_endpoint("openai") is None
    assert "openai" not in registry._provider_endpoints
    assert "openai" not in registry._provider_status_cache

    candidate = registry.get_personal_model_provider_endpoint("openai")
    assert candidate is not None
    assert candidate.provider_id == "openai"
    assert candidate.base_url == "https://api.openai.com/v1"
    assert candidate.api_key_env == "OPENAI_API_KEY"
    assert candidate.tenant_scoped is True
    assert candidate.fallback_eligible is False
    assert candidate.metadata["configuration_owner"] == "llm_provider_config"

    # A projection is NOT registration, readiness, model availability,
    # credential authorization, secret resolution, or a fallback candidate.
    assert "openai" not in registry._provider_endpoints
    assert "openai" not in registry._provider_status_cache
    assert registry.get_provider_endpoint("openai") is None

    # Ordinary workspace execution is unchanged when a shared key is present.
    configured["workspace_key"] = True
    workspace = registry.get_provider_endpoint("openai")
    assert workspace is not None
    assert workspace.provider_id == candidate.provider_id


@pytest.mark.parametrize("field,value", [
    ("enabled", False),
    ("provider_type", "local"),
    ("authentication", None),
    ("authentication", types.SimpleNamespace(
        type="none", api_key_env_var="OPENAI_API_KEY",
    )),
    ("authentication", types.SimpleNamespace(
        type="api_key", api_key_env_var="UNREGISTERED_KEY",
    )),
    ("endpoint_url", "http://api.openai.com/v1"),
    ("endpoint_url", "https://attacker.invalid/v1"),
    ("endpoint_url", "https://api.openai.com/v1/other"),
    ("endpoint_url", "https://user:password@api.openai.com/v1"),
    ("endpoint_url", "https://api.openai.com/v1?token=leak"),
])
def test_personal_vendor_projection_rejects_disallowed_config(
    provider_registry_service_module,
    personal_provider_without_workspace_key,
    field, value,
):
    _state, settings = personal_provider_without_workspace_key
    if field == "endpoint_url":
        settings.endpoint.base_url = value
    else:
        setattr(settings, field, value)
    registry = provider_registry_service_module.ProviderRegistryService()
    assert registry.get_personal_model_provider_endpoint("openai") is None
    assert registry.get_provider_endpoint("openai") is None
    assert "openai" not in registry._provider_endpoints


def test_personal_vendor_projection_does_not_include_local_or_unknown_targets(
    provider_registry_service_module, personal_provider_without_workspace_key
):
    registry = provider_registry_service_module.ProviderRegistryService()
    assert registry.get_personal_model_provider_endpoint("ollama-local") is None
    assert registry.get_personal_model_provider_endpoint("made-up-provider") is None
    assert registry.get_provider_endpoint("ollama-local") is not None
