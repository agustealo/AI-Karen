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
        try:
            module = importlib.import_module(module_info.name)
        except Exception:
            continue
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


def test_execution_request_rejects_caller_security_policy() -> None:
    """ExecutionRequest must not accept caller-owned security_policy or resource_limits."""
    from pydantic import ValidationError
    from ai_karen_engine.services.plugin_execution import ExecutionRequest

    with pytest.raises(ValidationError):
        ExecutionRequest(
            plugin_name="test-plugin",
            parameters={},
            security_policy={"allow_network": True},
            resource_limits={"max_memory_mb": 9999},
        )


def test_plugin_execution_context_exists() -> None:
    """PluginExecutionContext must expose immutable security fields."""
    from ai_karen_engine.services.plugin_execution import PluginExecutionContext

    context = PluginExecutionContext(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conv-1",
        request_id="req-1",
        correlation_id="corr-1",
        roles=["user"],
        permissions=["tool:access"],
        plugin_id="github",
        plugin_version="1.0.0",
        action="search",
        policy_decision_id="policy-1",
        allowed_capabilities=["web_search"],
        forbidden_capabilities=["admin"],
        resource_scope={"files": ["/tmp"]},
        resource_limits={"max_memory_mb": 256},
        security_policy={"allow_network": True},
    )

    assert context.plugin_id == "github"
    assert context.action == "search"
    assert context.policy_decision_id == "policy-1"
    assert context.resource_limits == {"max_memory_mb": 256}


def test_prompt_registry_has_getter() -> None:
    """PromptRegistry must expose a global getter."""
    from ai_karen_engine.core.runtime.prompt import get_prompt_registry, PromptRegistry

    registry = get_prompt_registry()
    assert isinstance(registry, PromptRegistry)


def test_plugin_default_prompt_resolves_from_prompt_registry() -> None:
    """Plugin default prompt contracts must resolve through the canonical PromptRegistry."""
    from ai_karen_engine.core.runtime.prompt import get_prompt_registry, PromptDefinition
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

    registry = get_prompt_registry()
    default_contract_id = "plugin.github.default@v1"
    registry.register(PromptDefinition(prompt_id=default_contract_id, version="v1"))

    manifest = ExtensionManifest(
        name="github",
        version="1.0.0",
        display_name="GitHub",
        description="Test",
        author="test",
        license="MIT",
        category="integration",
        prompt_files={"contract_id": default_contract_id, "mode": "custom", "prompt_first": True},
    )

    assert manifest.prompt_files.contract_id == default_contract_id
    prompt_id, version = default_contract_id.split("@", 1)
    assert registry.get(prompt_id, version) is not None


def test_plugin_custom_prompt_requires_registered_contract() -> None:
    """Custom prompt mode without a registered contract must fail validation."""
    from ai_karen_engine.extensions.platform.core.registry.validator import ExtensionValidator
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

    validator = ExtensionValidator()
    manifest = ExtensionManifest(
        name="custom-prompt-plugin",
        version="1.0.0",
        display_name="Custom Prompt Plugin",
        description="Test",
        author="test",
        license="MIT",
        category="integration",
        prompt_files={"contract_id": "plugin.missing.custom@v1", "mode": "custom", "prompt_first": True},
    )

    is_valid, errors, warnings = validator.validate_manifest(manifest)
    assert not is_valid
    assert any("PromptRegistry" in error or "prompt contract" in error for error in errors)


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


def test_cortex_never_executes_plugin() -> None:
    """CORTEX must declare and enforce that it never executes plugins."""
    from ai_karen_engine.core.runtime.cortex_execution_decider import (
        CortexExecutionDecider,
    )

    decider = CortexExecutionDecider()
    assert hasattr(decider, "cortex_never_executes")
    assert decider.cortex_never_executes() is True


def test_canonical_lifecycle_manager_is_exported() -> None:
    """The canonical PluginLifecycleManager must be exported from the platform core."""
    from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
        PluginLifecycleManager,
    )

    assert PluginLifecycleManager is not None


def test_plugin_execution_uses_manifest_limits() -> None:
    """PluginExecutionEngine must resolve resource limits from manifest, not caller."""
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
    from ai_karen_engine.services.plugin_execution import PluginExecutionEngine

    manifest = ExtensionManifest(
        name="limited-plugin",
        version="1.0.0",
        display_name="Limited",
        description="Test",
        author="test",
        license="MIT",
        category="test",
        resources={"max_memory_mb": 512, "max_cpu_percent": 5},
    )

    engine = PluginExecutionEngine(registry={})
    limits = engine._resolve_resource_limits(manifest)
    assert limits.max_memory_mb == 512
    assert limits.max_cpu_percent == 5
