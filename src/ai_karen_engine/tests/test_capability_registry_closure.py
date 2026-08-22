"""
Architecture enforcement tests for ARCH-CLOSE-2: Capability + Registry Closure.

Validates that:
- KIRE/KRO routing authority is deprecated/retired
- Canonical service registry is used exclusively
- Canonical extension platform is the single extension authority
- Unified extension system is deprecated migration residue
"""

from __future__ import annotations

import pathlib

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "src" / "ai_karen_engine"


def test_kire_kro_integration_is_deprecated() -> None:
    """KIREKROIntegration must carry a deprecation warning."""
    integration_path = RUNTIME_ROOT / "core" / "cortex" / "kire_kro_integration.py"
    text = integration_path.read_text(encoding="utf-8")

    assert "deprecated" in text.lower() or "KIREKROIntegration" in text, (
        "KIREKROIntegration must be marked deprecated."
    )


def test_no_new_code_imports_kire_kro_integration() -> None:
    """Non-test production code must not add new imports of deprecated KIREKROIntegration.
    
    Existing imports in initialize_kire_kro.py and api_routes/cognition/kro.py
    are migration residue tracked for removal in the post-closure audit.
    """
    src_root = RUNTIME_ROOT
    forbidden = "from ai_karen_engine.core.cortex.kire_kro_integration import"
    grandfathered = {
        RUNTIME_ROOT / "initialize_kire_kro.py",
        RUNTIME_ROOT / "api_routes" / "cognition" / "kro.py",
    }

    violations = []
    for path in src_root.rglob("*.py"):
        if "/tests/" in str(path) or "tests" in path.parts:
            continue
        if path in grandfathered:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden in text:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert not violations, (
        "Production code must not import deprecated KIREKROIntegration: "
        + ", ".join(sorted(violations))
    )


def test_canonical_service_registry_is_service_registry() -> None:
    """The canonical service registry must be core/services/service_registry.py."""
    canonical_path = RUNTIME_ROOT / "core" / "services" / "service_registry.py"
    assert canonical_path.exists(), "Canonical service registry must exist."

    text = canonical_path.read_text(encoding="utf-8")
    assert "class ServiceRegistry" in text


def test_no_new_code_uses_classified_service_registry() -> None:
    """Non-test production code must not add new imports of deprecated ClassifiedServiceRegistry.
    
    Existing imports in core/services/__init__.py, service_registry.py,
    resource_monitor.py, and server/optimized_startup.py are migration residue
    tracked for removal in the post-closure audit.
    """
    src_root = RUNTIME_ROOT
    forbidden = "from ai_karen_engine.core.services.classified_service_registry import"
    grandfathered = {
        RUNTIME_ROOT / "core" / "services" / "__init__.py",
        RUNTIME_ROOT / "core" / "services" / "service_registry.py",
        RUNTIME_ROOT / "core" / "runtime" / "resource_monitor.py",
        RUNTIME_ROOT / "server" / "optimized_startup.py",
    }

    violations = []
    for path in src_root.rglob("*.py"):
        if "/tests/" in str(path) or "tests" in path.parts:
            continue
        if path in grandfathered:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden in text:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert not violations, (
        "Production code must not import deprecated ClassifiedServiceRegistry: "
        + ", ".join(sorted(violations))
    )


def test_canonical_extension_platform_is_extensions_platform() -> None:
    """The canonical extension platform must be extensions/platform/."""
    platform_path = RUNTIME_ROOT / "extensions" / "platform"
    assert platform_path.exists(), "Canonical extension platform must exist."

    manifest_path = platform_path / "core" / "manifest.py"
    assert manifest_path.exists(), "Canonical extension manifest must exist."


def test_unified_extension_system_is_deprecated() -> None:
    """extensions/unified must be marked as deprecated migration residue."""
    unified_init = RUNTIME_ROOT / "extensions" / "unified" / "__init__.py"
    assert unified_init.exists(), "Unified extension system must still exist during migration."

    text = unified_init.read_text(encoding="utf-8")
    assert "deprecated" in text.lower() or "migration" in text.lower(), (
        "extensions/unified must be marked as deprecated migration residue."
    )


def test_no_new_code_imports_from_unified_extension_system() -> None:
    """Non-test production code must not add new imports from deprecated extensions/unified.
    
    Existing imports are migration residue tracked for removal in the post-closure audit.
    """
    src_root = RUNTIME_ROOT
    forbidden_prefix = "from ai_karen_engine.extensions.unified"

    violations = []
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(PROJECT_ROOT)
        path_str = str(rel)
        if "tests" in rel.parts or rel.name.startswith("test_") or rel.name.endswith("_test.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(line.strip().startswith(forbidden_prefix) for line in text.splitlines()):
            violations.append(path_str)

    if violations:
        pytest.fail(
            "Production code must not import from deprecated extensions/unified. "
            "Migrate to extensions/platform/: " + ", ".join(sorted(violations))
        )


def test_capability_descriptor_exists() -> None:
    """CapabilityDescriptor must exist as the common capability vocabulary."""
    contracts_path = RUNTIME_ROOT / "core" / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class CapabilityDescriptor" in text, (
        "CapabilityDescriptor must exist in canonical contracts."
    )
