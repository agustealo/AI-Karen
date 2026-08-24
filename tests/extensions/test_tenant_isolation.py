"""Tests for tenant isolation and permission enforcement."""

from __future__ import annotations

import pytest

from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionManifest,
    TenantScope,
)
from ai_karen_engine.extensions.discovery import ExtensionDiscovery


def test_global_tenant_scope_rejected_by_validator():
    discovery = ExtensionDiscovery()
    manifest = ExtensionManifest(
        id="bad-tenant",
        name="bad-tenant",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Bad tenant scope",
        entrypoint="handler:Test",
        capabilities=[],
        intents=[],
        required_permissions=[],
        optional_permissions=[],
        required_roles=[],
        tenant_scope=TenantScope.GLOBAL,
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
    errors = discovery.validate_manifest(manifest)
    assert any("global" in e for e in errors)


def test_multi_tenant_without_allowlist_warns():
    discovery = ExtensionDiscovery()
    manifest = ExtensionManifest(
        id="multi-tenant",
        name="multi-tenant",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Multi-tenant without allowlist",
        entrypoint="handler:Test",
        capabilities=[],
        intents=[],
        required_permissions=[],
        optional_permissions=[],
        required_roles=[],
        tenant_scope=TenantScope.MULTI,
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
    errors = discovery.validate_manifest(manifest)
    assert any("allowed_tenant_ids" in e for e in errors)
