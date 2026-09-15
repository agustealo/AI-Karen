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


@pytest.mark.asyncio
async def test_register_and_get():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    assert await registry.get("echo") is registration


@pytest.mark.asyncio
async def test_duplicate_version_raises():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    with pytest.raises(ValueError):
        await registry.register(registration)


@pytest.mark.asyncio
async def test_unregister():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    await registry.unregister("echo")
    assert await registry.get("echo") is None


@pytest.mark.asyncio
async def test_get_by_capability():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    results = await registry.get_by_capability("test")
    assert len(results) == 1
    assert results[0].manifest.id == "echo"


@pytest.mark.asyncio
async def test_get_by_intent():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    results = await registry.get_by_intent("test")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_list_enabled():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(manifest=_manifest("echo"), state=ExtensionLifecycleState.DISCOVERED)
    await registry.register(registration)
    registration.state = ExtensionLifecycleState.ENABLED
    assert len(await registry.list_enabled()) == 1


@pytest.mark.asyncio
async def test_not_found_error():
    registry = ExtensionRegistry()
    with pytest.raises(ExtensionNotFoundError):
        await registry.unregister("missing")
