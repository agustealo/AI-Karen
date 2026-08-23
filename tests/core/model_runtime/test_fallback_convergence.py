from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from enum import Enum
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

    logging_pkg = "ai_karen_engine.core.logging"
    if logging_pkg not in sys.modules:
        logging_mod = types.ModuleType(logging_pkg)
        logging_mod.get_logger = lambda name: __import__("logging").getLogger(name)
        logging_mod.__package__ = logging_pkg
        sys.modules[logging_pkg] = logging_mod

    phm_pkg = "ai_karen_engine.core.model_runtime.provider_health_monitor"
    if phm_pkg not in sys.modules:
        phm_mod = types.ModuleType(phm_pkg)
        phm_mod.__package__ = phm_pkg

        class HealthStatus(str, Enum):
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
    """Load provider_registry_service without triggering package __init__."""
    path = CORE_MODEL_RUNTIME / "provider_registry_service.py"
    return _load_module("prs_for_fallback_test", path)


def test_fallback_chain_manager_file_deleted() -> None:
    """integrations/fallback_chain_manager.py must be retired."""
    fallback_mgr = SRC / "integrations" / "fallback_chain_manager.py"
    assert not fallback_mgr.exists(), "fallback_chain_manager.py must be deleted"


def test_fallback_chains_readme_deleted() -> None:
    """integrations/README_FALLBACK_CHAINS.md must be retired."""
    readme = SRC / "integrations" / "README_FALLBACK_CHAINS.md"
    assert not readme.exists(), "README_FALLBACK_CHAINS.md must be deleted"


def test_no_fallback_chain_manager_imports_in_source() -> None:
    """No source file should import from integrations.fallback_chain_manager."""
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        if "test_" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "from ai_karen_engine.integrations.fallback_chain_manager" in line:
                violations.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not violations, (
        "No source file should import from integrations.fallback_chain_manager:\n"
        + "\n".join(violations)
    )


def test_canonical_fallback_selects_alternate_provider(
    provider_registry_service_module,
) -> None:
    """When preferred provider is unavailable, canonical fallback selects alternate."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
    ProviderCapability = provider_registry_service_module.ProviderCapability

    registry = ProviderRegistryService()

    class FailingProvider:
        def generate_text(self, prompt: str) -> str:
            raise RuntimeError("Provider unavailable")

    registry.register_provider(
        "openai",
        FailingProvider,
        description="Preferred but failing provider",
        requires_api_key=True,
    )

    class FallbackProvider:
        def generate_text(self, prompt: str) -> str:
            return "response"

    registry.register_provider(
        "local_gguf",
        FallbackProvider,
        description="Available fallback provider",
        requires_api_key=False,
    )

    preferred_status = registry.get_provider_status("openai")
    assert preferred_status is not None
    assert not preferred_status.is_available, "Preferred should be unavailable (no API key)"

    fallback_status = registry.get_provider_status("local_gguf")
    assert fallback_status is not None
    assert fallback_status.is_available, "Fallback should be available"

    selected = registry.select_provider_with_fallback(
        preferred_provider="openai",
        capability=ProviderCapability.TEXT_GENERATION,
    )

    assert selected is not None, "Should have selected an alternate provider"
    assert selected != "openai", "Should NOT select the unavailable preferred provider"
    selected_status = registry.get_provider_status(selected)
    assert selected_status is not None and selected_status.is_available, (
        f"Selected provider {selected} should be available"
    )


def test_canonical_fallback_uses_configured_chain(
    provider_registry_service_module,
) -> None:
    """Canonical fallback follows the configured chain order."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
    ProviderCapability = provider_registry_service_module.ProviderCapability

    registry = ProviderRegistryService()

    class WorkingProvider:
        def generate_text(self, prompt: str) -> str:
            return "response"

    registry.register_provider(
        "openai",
        WorkingProvider,
        requires_api_key=True,
    )
    registry.register_provider(
        "anthropic",
        WorkingProvider,
        requires_api_key=True,
    )
    registry.register_provider(
        "builtin_vllm",
        WorkingProvider,
        requires_api_key=False,
    )

    registry.create_fallback_chain(
        "test_chain",
        primary="openai",
        fallbacks=["anthropic", "builtin_vllm"],
        capability_required=ProviderCapability.TEXT_GENERATION,
    )

    selected = registry.select_provider_with_fallback(
        fallback_chain_name="test_chain",
        capability=ProviderCapability.TEXT_GENERATION,
    )

    assert selected is not None, "Should have selected a provider"
    assert selected != "openai", "Should not select unavailable primary"
    assert selected != "anthropic", "Should not select unavailable secondary"
    assert selected == "builtin_vllm", (
        f"Should follow chain to builtin_vllm, got {selected}"
    )


def test_canonical_fallback_reports_degraded_metadata(
    provider_registry_service_module,
) -> None:
    """Canonical fallback execution emits degraded metadata for telemetry."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
    ProviderCapability = provider_registry_service_module.ProviderCapability

    registry = ProviderRegistryService()

    class WorkingProvider:
        def generate_text(self, prompt: str) -> str:
            return "response"

    registry.register_provider(
        "openai",
        WorkingProvider,
        requires_api_key=True,
    )
    registry.register_provider(
        "builtin_vllm",
        WorkingProvider,
        requires_api_key=False,
    )

    recommendations = registry.get_provider_recommendations("openai")

    assert recommendations["failed_provider"] == "openai"
    assert len(recommendations["alternatives"]) > 0, (
        "Should recommend alternate providers"
    )
    assert "builtin_vllm" in recommendations["alternatives"], (
        "Should recommend the available alternate"
    )
