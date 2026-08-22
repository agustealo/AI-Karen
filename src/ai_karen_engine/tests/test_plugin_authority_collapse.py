"""
Architecture proof tests for plugin authority collapse.

Validates that the canonical ExtensionManifest is the single source of truth,
unified components import from the canonical manifest, and the old duplicate
manifest schema has been removed.
"""

from __future__ import annotations

import importlib
import pkgutil
import pathlib

import pytest


def test_only_extension_manifest_is_canonical() -> None:
    """There must be exactly one ExtensionManifest definition in the source tree."""
    manifest_paths = []

    src_root = pathlib.Path(__file__).resolve().parents[1]
    for path in src_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "class ExtensionManifest(" in text:
            manifest_paths.append(path)

    assert len(manifest_paths) == 1, (
        "Multiple ExtensionManifest definitions found: "
        f"{manifest_paths}. Canonical manifest must be unique."
    )
    assert manifest_paths[0].name == "manifest.py"
    assert "extensions/platform/core" in str(manifest_paths[0])


def test_legacy_unified_manifest_removed() -> None:
    """The legacy unified manifest file must no longer exist."""
    src_root = pathlib.Path(__file__).resolve().parents[1]
    legacy = src_root / "ai_karen_engine" / "extensions" / "unified" / "manifest.py"
    assert not legacy.exists(), "Legacy unified manifest file still exists."


def test_unified_imports_use_canonical_manifest() -> None:
    """Unified extension modules must import ExtensionManifest from the canonical manifest."""
    src_root = pathlib.Path(__file__).resolve().parents[1]
    unified_core = src_root / "ai_karen_engine" / "extensions" / "unified" / "core"
    bad_imports = []

    if not unified_core.exists():
        pytest.skip("Unified core package not present.")

    for module_info in pkgutil.walk_packages([str(unified_core)], prefix="ai_karen_engine.extensions.unified.core."):
        module = importlib.import_module(module_info.name)
        source = pathlib.Path(module.__file__ or "")
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        if "from ..manifest import ExtensionManifest" in text:
            bad_imports.append(source)

    assert not bad_imports, (
        "Unified modules still import ExtensionManifest from the legacy unified manifest: "
        f"{bad_imports}"
    )


def test_prompt_mode_defaults_exist() -> None:
    """Canonical manifest must define PromptMode with DEFAULT, CUSTOM, and NONE."""
    from ai_karen_engine.extensions.platform.core.manifest import (
        ExtensionManifest,
        ExtensionPromptFiles,
        ExtensionCapabilities,
        PromptMode,
    )

    assert PromptMode.DEFAULT == "default"
    assert PromptMode.CUSTOM == "custom"
    assert PromptMode.NONE == "none"

    manifest = ExtensionManifest(name="test-plugin", version="1.0.0", display_name="Test", description="Test", author="test", license="MIT", category="test")
    assert manifest.prompt_files.mode == PromptMode.DEFAULT
    assert manifest.prompt_files.prompt_first is True
    assert manifest.capabilities.prompt_first is True


def test_prompt_first_defaults_to_true() -> None:
    """Generative plugin manifests must default to prompt-first behavior."""
    from ai_karen_engine.extensions.platform.core.manifest import (
        ExtensionManifest,
        PromptMode,
    )

    manifest = ExtensionManifest(
        name="llm-plugin",
        version="1.0.0",
        display_name="LLM Plugin",
        description="Test",
        author="test",
        license="MIT",
        category="ai",
    )

    assert manifest.prompt_files.prompt_first is True
    assert manifest.prompt_files.mode == PromptMode.DEFAULT


def test_legacy_manifest_schema_removed() -> None:
    """The old PluginManifest and PluginMetadata schemas must not be importable from plugin_discovery."""
    import ai_karen_engine.services.plugin_discovery as pd

    assert not hasattr(pd, "PluginManifest"), "Legacy PluginManifest schema still exists."
    assert not hasattr(pd, "PluginMetadata"), "Legacy PluginMetadata schema still exists."
    assert not hasattr(pd, "PluginStatus"), "Legacy PluginStatus enum still exists."
    assert not hasattr(pd, "PluginType"), "Legacy PluginType enum still exists."


def test_execution_request_has_security_fields() -> None:
    """ExecutionRequest still accepts security_policy/resource_limits, but the
    execution engine must not use caller-supplied values as policy truth.

    This test documents the current model surface; enforcement happens in
    PluginExecutionEngine.
    """
    from ai_karen_engine.services.plugin_execution import ExecutionRequest

    request = ExecutionRequest(
        plugin_name="test-plugin",
        parameters={},
        security_policy={"allow_network": True},
        resource_limits={"max_memory_mb": 9999},
    )

    assert request.security_policy is not None
    assert request.resource_limits is not None


def test_only_one_plugin_registry_class_exists() -> None:
    """There must be exactly one canonical PluginRegistry class."""
    registry_paths = []

    src_root = pathlib.Path(__file__).resolve().parents[1]
    for path in src_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "class PluginRegistry(" in text:
            registry_paths.append(path)

    assert len(registry_paths) == 1, (
        "Multiple PluginRegistry definitions found: "
        f"{registry_paths}. Canonical registry must be unique."
    )
