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
            UNKNOWN = "unknown"

        class ProviderHealthMonitor:
            def __init__(self, registry=None, check_interval=300, cache_ttl=300):
                self._registry = registry
                self.check_interval = check_interval
                self._cache_ttl = cache_ttl
                self._health_cache = {}
                self._prev_statuses = {}

            def get_all_provider_names(self):
                return []

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
        assert "chat" in endpoint.capabilities

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
            required_capabilities={"chat_completion", "streaming_text"},
            healthy_only=False,
        )
        target_ids = [t.provider_id for t in targets]
        assert "builtin_vllm" in target_ids

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
