"""Tests for canonical extension lifecycle."""

from __future__ import annotations

import pytest

from ai_karen_engine.extensions.contracts import (
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
)
from ai_karen_engine.extensions.errors import ExtensionNotFoundError
from ai_karen_engine.extensions.lifecycle import ExtensionLifecycleManager


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        id="echo",
        name="echo",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Test",
        entrypoint="handler:Test",
        capabilities=[],
        intents=[],
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


def test_valid_transition():
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(manifest=_manifest(), state=ExtensionLifecycleState.DISCOVERED)})()
    lm = ExtensionLifecycleManager(registry=registry)
    lm.transition("echo", ExtensionLifecycleState.VALIDATED)
    assert lm.get_health("echo").state == ExtensionLifecycleState.VALIDATED


def test_invalid_transition_raises():
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(manifest=_manifest(), state=ExtensionLifecycleState.ENABLED)})()
    lm = ExtensionLifecycleManager(registry=registry)
    with pytest.raises(Exception):
        lm.transition("echo", ExtensionLifecycleState.DISCOVERED)


def test_health_records():
    lm = ExtensionLifecycleManager()
    lm.record_health("echo", health="healthy")
    record = lm.get_health("echo")
    assert record is not None
    assert record.health == "healthy"
