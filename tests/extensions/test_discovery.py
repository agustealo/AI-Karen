"""Tests for the single plugin discovery and projection authority."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.contracts import (
    ExtensionLifecycleState,
    TenantScope,
    TrustTier,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel


def _write_plugin(root: Path, *, default_enabled: bool = True) -> None:
    plugin_dir = root / "echo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin_manifest.json").write_text(
        json.dumps(
            {
                "name": "echo",
                "version": "1.0.0",
                "display_name": "Echo",
                "description": "Echo plugin used to prove canonical discovery.",
                "author": "Kari",
                "license": "MIT",
                "category": "test",
                "entrypoint": "handler:MainExtension",
                "capabilities": {
                    "provides_ui": False,
                    "provides_api": True,
                    "prompt_first": True,
                },
                "rbac": {
                    "allowed_roles": ["user"],
                    "default_enabled": default_enabled,
                },
                "config_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additional_properties": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "handler.py").write_text(
        "class MainExtension:\n    pass\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_plugin_kernel_uses_platform_catalog_as_discovery_truth(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    kernel = PluginKernel(tmp_path)

    count = await kernel.refresh()

    assert count == 1
    record = kernel.get_record("echo")
    assert record is not None
    assert record["manifest"].name == "echo"
    assert record["manifest"].display_name == "Echo"
    assert record["status"] == ExtensionLifecycleState.ENABLED.value

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.manifest.id == "echo"
    assert registration.manifest.tenant_scope is TenantScope.SINGLE
    assert [cap.id for cap in registration.manifest.capabilities] == ["execute"]
    assert registration.manifest.input_schema["required"] == ["message"]


@pytest.mark.asyncio
async def test_custom_plugin_root_is_not_promoted_to_first_party_trust(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.manifest.trust_tier is TrustTier.UNTRUSTED


@pytest.mark.asyncio
async def test_manifest_default_disabled_projects_to_disabled_runtime_state(tmp_path: Path) -> None:
    _write_plugin(tmp_path, default_enabled=False)
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.state is ExtensionLifecycleState.DISABLED


def test_duplicate_top_level_discovery_and_manifest_loaders_are_retired() -> None:
    root = Path(__file__).parents[2] / "src" / "ai_karen_engine" / "extensions"
    assert not (root / "discovery.py").exists()
    assert not (root / "manifest.py").exists()
