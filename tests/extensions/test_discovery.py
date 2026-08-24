"""Tests for canonical extension discovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.contracts import TenantScope
from ai_karen_engine.extensions.discovery import ExtensionDiscovery


@pytest.mark.asyncio
async def test_discover_echo_fixture(tmp_path: Path):
    extensions_dir = tmp_path / "plugins"
    extension_dir = extensions_dir / "echo"
    extension_dir.mkdir(parents=True)
    manifest = {
        "id": "echo",
        "name": "echo",
        "version": "1.0.0",
        "plugin_api_version": "1.0",
        "description": "Echo test extension",
        "entrypoint": "handler:EchoExtension",
        "capabilities": [{"id": "echo", "version": "1.0.0"}],
        "intents": ["echo"],
        "required_permissions": [],
        "optional_permissions": [],
        "required_roles": [],
        "tenant_scope": "single",
        "allowed_tenant_ids": [],
        "input_schema": {},
        "output_schema": {},
        "side_effect_level": "none",
        "timeout_ms": 5000,
        "max_retries": 1,
        "enabled_by_default": False,
        "trusted_ui": False,
        "dependencies": [],
        "metadata": {},
    }
    (extension_dir / "extension_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (extension_dir / "handler.py").write_text("", encoding="utf-8")

    discovery = ExtensionDiscovery(directories=[extensions_dir])
    discovered = await discovery.discover()
    assert "echo" in discovered
    assert discovered["echo"].manifest is not None
    assert discovered["echo"].manifest.id == "echo"


def test_global_tenant_scope_invalid():
    discovery = ExtensionDiscovery()
    manifest = {
        "id": "bad",
        "name": "bad",
        "version": "1.0.0",
        "plugin_api_version": "1.0",
        "description": "Bad extension",
        "entrypoint": "handler:Bad",
        "capabilities": [],
        "intents": [],
        "required_permissions": [],
        "optional_permissions": [],
        "required_roles": [],
        "tenant_scope": "global",
        "allowed_tenant_ids": [],
        "input_schema": {},
        "output_schema": {},
        "side_effect_level": "none",
        "timeout_ms": 5000,
        "max_retries": 1,
        "enabled_by_default": False,
        "trusted_ui": False,
        "dependencies": [],
        "metadata": {},
    }
    from ai_karen_engine.extensions.contracts import ExtensionManifest

    m = ExtensionManifest(**manifest)
    errors = discovery.validate_manifest(m)
    assert any("global" in e for e in errors)


def test_multi_tenant_without_allowlist_warns():
    discovery = ExtensionDiscovery()
    manifest = {
        "id": "multi-tenant",
        "name": "multi-tenant",
        "version": "1.0.0",
        "plugin_api_version": "1.0",
        "description": "Multi-tenant without allowlist",
        "entrypoint": "handler:Test",
        "capabilities": [],
        "intents": [],
        "required_permissions": [],
        "optional_permissions": [],
        "required_roles": [],
        "tenant_scope": "multi",
        "allowed_tenant_ids": [],
        "input_schema": {},
        "output_schema": {},
        "side_effect_level": "none",
        "timeout_ms": 5000,
        "max_retries": 1,
        "enabled_by_default": False,
        "trusted_ui": False,
        "dependencies": [],
        "metadata": {},
    }
    from ai_karen_engine.extensions.contracts import ExtensionManifest

    m = ExtensionManifest(**manifest)
    errors = discovery.validate_manifest(m)
    assert any("allowed_tenant_ids" in e for e in errors)
