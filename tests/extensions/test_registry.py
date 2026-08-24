"""Tests for the canonical extension registry."""

from __future__ import annotations

import pytest

from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
)
from ai_karen_engine.extensions.registry import ExtensionRegistry
from ai_karen_engine.extensions.errors import ExtensionNotFoundError


def _manifest(plugin_id: str = "test") -> ExtensionManifest:
    return ExtensionManifest(
        id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        plugin_api_version="1.0",
        description="Test extension",
        entrypoint="handler:Test",
        capabilities=[ExtensionCapability(id="test", version="1.0.0")],
        intents=["test"],
        required_permissions=[],
        optional_permissions=[],
        required_roles=[],
        tenant_scope="single",
        allowed_tenant_ids=[],
        input_schema={},
        output_schema={},
        side_effect_level="none",
        timeout_ms=5000,
        max_retries=1,
        enabled_by_default=False,
        trusted_ui=False,
        dependencies=[],
    )


def test_register_and_get():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    assert registry.get("echo") is registration


def test_duplicate_version_raises():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    with pytest.raises(ValueError):
        registry.register(registration)


def test_unregister():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    registry.unregister("echo")
    assert registry.get("echo") is None


def test_get_by_capability():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    results = registry.get_by_capability("test")
    assert len(results) == 1
    assert results[0].manifest.id == "echo"


def test_get_by_intent():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    results = registry.get_by_intent("test")
    assert len(results) == 1


def test_list_enabled():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    registry.register(registration)
    registration.state = ExtensionLifecycleState.ENABLED
    assert len(registry.list_enabled()) == 1


def test_not_found_error():
    registry = ExtensionRegistry()
    with pytest.raises(ExtensionNotFoundError):
        registry.unregister("missing")
