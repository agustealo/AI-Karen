from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
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


@pytest.mark.asyncio
async def test_force_refresh_preserves_disabled_state(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()

    assert await service.disable_plugin("alpha-plugin") is True
    before = service.kernel.runtime_registry.get("alpha-plugin")
    assert before is not None
    assert before.state is ExtensionLifecycleState.DISABLED

    count = await service.refresh_plugins()

    assert count == 1
    after = service.kernel.runtime_registry.get("alpha-plugin")
    assert after is not None
    assert after.state is ExtensionLifecycleState.DISABLED
    assert (await service.get_plugin_info("alpha-plugin"))["status"] == "disabled"


@pytest.mark.asyncio
async def test_refresh_does_not_reenable_disabled_plugin(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    assert await service.disable_plugin("alpha-plugin") is True

    await service.discover_plugins(force_refresh=True)
    registration = service.kernel.runtime_registry.get("alpha-plugin")

    assert registration is not None
    assert registration.state is ExtensionLifecycleState.DISABLED
    assert service.get_plugins_by_status("enabled") == []
