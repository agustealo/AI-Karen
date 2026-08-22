from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import types
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"
CORE_MODEL_RUNTIME = SRC / "core" / "model_runtime"

# Verify paths resolve correctly
assert ROOT.exists(), f"ROOT does not exist: {ROOT}"
assert CORE_MODEL_RUNTIME.exists(), f"CORE_MODEL_RUNTIME does not exist: {CORE_MODEL_RUNTIME}"


def _load_module(name: str, path: pathlib.Path):
    """Load a module in isolation, mocking heavy dependencies."""
    # Mock heavy deps that aren't needed for these tests
    numpy_mock = types.ModuleType("numpy")
    sys.modules.setdefault("numpy", numpy_mock)

    # Break the package __init__ chain by pre-loading a mock package
    pkg_name = "ai_karen_engine.core.model_runtime"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(CORE_MODEL_RUNTIME)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    # Also mock the parent packages to avoid init issues
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

        class HealthStatus(str, Enum):
            HEALTHY = "healthy"
            DEGRADED = "degraded"
            UNHEALTHY = "unhealthy"
            UNKNOWN = "unknown"

        phm_mod.HealthStatus = HealthStatus
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
    return _load_module("provider_registry_service_isolated", path)


def test_provider_registry_service_owns_provider_state(
    provider_registry_service_module,
) -> None:
    """ProviderRegistryService must maintain its own provider registration state."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService

    registry = ProviderRegistryService(seed_from_legacy=False)
    assert hasattr(registry, "_provider_registrations")
    assert isinstance(registry._provider_registrations, dict)


def test_provider_registry_service_has_no_legacy_registry_dependency() -> None:
    """core/model_runtime must not import integrations registries at module level.

    Exception: one explicitly documented temporary migration seed import
    in provider_registry_service.py is allowed during INTEGRATIONS-2B.1.
    """
    violations: list[str] = []
    allowed_temp_seed = {
        "provider_registry_registry_service.py",
    }
    for path in CORE_MODEL_RUNTIME.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"from\s+ai_karen_engine\.integrations\.(provider_registry|llm_registry)\s+import", line):
                # Allow only the documented temporary migration seed
                if "TEMP-MIGRATION" in line or "TEMPORARY" in line:
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {stripped}")
    assert not violations, (
        "core/model_runtime must not import from integrations registries:\n"
        + "\n".join(violations)
    )


def test_provider_registry_service_returns_registered_providers(
    provider_registry_service_module,
) -> None:
    """Canonical registry returns providers registered through canonical path."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
    ModelInfo = provider_registry_service_module.ModelInfo

    # Mock the LLMRouter lazy load to avoid deep import chain in test env
    mock_router = MagicMock()
    mock_router.provider_health = {}
    with patch.object(
        ProviderRegistryService, "_get_llm_router", return_value=mock_router
    ):
        registry = ProviderRegistryService(seed_from_legacy=False)

        class DummyProvider:
            def generate_text(self, prompt: str) -> str:
                return ""

        registry.register_provider(
            "dummy_test_provider",
            DummyProvider,
            description="Test provider",
            models=[ModelInfo(name="dummy-v1")],
        )

    assert "dummy_test_provider" in registry.get_all_provider_names()
    models = registry.get_registered_models("dummy_test_provider", healthy_only=False)
    assert "dummy-v1" in models


def test_provider_registry_service_returns_model_capabilities(
    provider_registry_service_module,
) -> None:
    """Canonical registry reports capabilities for registered providers."""
    ProviderRegistryService = provider_registry_service_module.ProviderRegistryService
    ProviderCapability = provider_registry_service_module.ProviderCapability

    # Mock the LLMRouter lazy load to avoid deep import chain in test env
    mock_router = MagicMock()
    mock_router.provider_health = {}
    with patch.object(
        ProviderRegistryService, "_get_llm_router", return_value=mock_router
    ):
        registry = ProviderRegistryService(seed_from_legacy=False)

        class DummyProvider:
            def generate_text(self, prompt: str) -> str:
                return ""

            def get_embeddings(self, text: str) -> list[float]:
                return []

        registry.register_provider(
            "capability_test_provider",
            DummyProvider,
            description="Test provider with capabilities",
        )

    status = registry.get_provider_status("capability_test_provider")
    assert status is not None
    assert ProviderCapability.TEXT_GENERATION in status.capabilities
    assert ProviderCapability.EMBEDDINGS in status.capabilities
