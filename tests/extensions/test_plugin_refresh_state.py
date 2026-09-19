from __future__ import annotations

import json
from pathlib import Path

import pytest

import ai_karen_engine.services.plugin_discovery as plugin_discovery
from ai_karen_engine.services.plugin_discovery import PluginRegistry
from ai_karen_engine.services.plugin_service import PluginService


def _write_plugin(root: Path) -> None:
    plugin_dir = root / "alpha-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "handler.py").write_text(
        "class MainExtension:\n    pass\n", encoding="utf-8"
    )
    (plugin_dir / "plugin_manifest.json").write_text(
        json.dumps(
            {
                "name": "alpha-plugin",
                "version": "1.0.0",
                "display_name": "Alpha Plugin",
                "description": "Refresh-state fixture",
                "author": "Kari",
                "license": "MIT",
                "category": "test",
                "entrypoint": "handler:MainExtension",
            }
        ),
        encoding="utf-8",
    )


def _registry(root: Path) -> PluginRegistry:
    registry = PluginRegistry(marketplace_path=root, core_plugins_path=root)
    registry.extensions_core_path = root
    registry.legacy_marketplace_path = root / "missing-marketplace"
    registry.legacy_core_plugins_path = root / "missing-core"
    return registry


def test_legacy_plugin_metadata_symbol_remains_retired() -> None:
    assert not hasattr(plugin_discovery, "PluginMetadata")


@pytest.mark.asyncio
async def test_force_refresh_preserves_disabled_state(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    registry = _registry(tmp_path)

    await registry.discover_plugins()
    registry.plugins["alpha-plugin"]["status"] = "disabled"

    refreshed = await registry.discover_plugins(force_refresh=True)

    assert refreshed["alpha-plugin"]["status"] == "disabled"
    assert registry.plugins["alpha-plugin"]["status"] == "disabled"


@pytest.mark.asyncio
async def test_service_reload_does_not_reenable_disabled_plugin(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    registry = _registry(tmp_path)
    await registry.discover_plugins()
    registry.plugins["alpha-plugin"]["status"] = "disabled"

    service = PluginService()
    service.initialized = True
    service.registry = registry

    count = await service.refresh_plugins()

    assert count == 1
    assert registry.plugins["alpha-plugin"]["status"] == "disabled"
    assert registry.get_plugins_by_status("registered") == []
