"""Uninstall refresh cannot retain state for a removed plugin."""
import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.services.plugin_service import PluginService


def _write_plugin(root: Path, plugin_id: str) -> None:
    directory = root / plugin_id
    directory.mkdir()
    (directory / "handler.py").write_text(
        "class MainExtension:\\n    pass\\n", encoding="utf-8"
    )
    (directory / "plugin_manifest.json").write_text(
        json.dumps({
            "name": plugin_id,
            "version": "1.0.0",
            "display_name": plugin_id,
            "description": "Loaded-package retirement contract",
            "author": "Kari",
            "license": "MIT",
            "category": "test",
            "entrypoint": "handler:MainExtension",
        }), encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_refresh_prunes_uninstalled_plugin_disable_state(tmp_path: Path):
    kernel = PluginKernel(tmp_path)
    kernel._disabled.update({"removed_plugin", "other_removed_plugin"})

    class EmptyCatalog:
        async def refresh(self):
            return None

        def list_discovered(self):
            return []

        def get_metadata(self, plugin_id):
            return None

    kernel.catalog_registry = EmptyCatalog()
    await kernel.refresh()
    assert kernel._disabled == set()
    assert kernel.get_record("removed_plugin") is None


@pytest.mark.asyncio
async def test_refresh_retires_removed_loaded_plugin_and_rejects_stale_cache(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _write_plugin(tmp_path, "retired")
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    instance = SimpleNamespace(
        context=SimpleNamespace(extension_dir=tmp_path / "retired"),
        is_shutdown=lambda: False,
        _shutdown=AsyncMock(),
    )
    kernel.loader._loaded_extensions["retired"] = instance

    import shutil
    shutil.rmtree(tmp_path / "retired")
    await service.refresh_plugins()
    instance._shutdown.assert_awaited_once()
    assert kernel.loader.get_loaded_extensions() == {}
    assert kernel.runtime_registry.get("retired") is None
    assert kernel.get_record("retired") is None


@pytest.mark.asyncio
async def test_refresh_preserves_unchanged_loaded_plugin(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _write_plugin(tmp_path, "steady")
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    instance = SimpleNamespace(
        context=SimpleNamespace(extension_dir=tmp_path / "steady"),
        is_shutdown=lambda: False,
        _shutdown=AsyncMock(),
    )
    kernel.loader._loaded_extensions["steady"] = instance
    await service.refresh_plugins()
    instance._shutdown.assert_not_awaited()
    assert kernel.loader.get_loaded_extensions()["steady"] is instance


@pytest.mark.asyncio
async def test_changed_plugin_retired_and_failure_fails_closed(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _write_plugin(tmp_path, "replaced")
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    instance = SimpleNamespace(
        context=SimpleNamespace(extension_dir=tmp_path / "replaced"),
        is_shutdown=lambda: False,
        _shutdown=AsyncMock(side_effect=RuntimeError("private handler failure")),
    )
    kernel.loader._loaded_extensions["replaced"] = instance
    with (tmp_path / "replaced" / "handler.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# new handler code changes source fingerprint\n")
    with pytest.raises(RuntimeError, match="private handler failure"):
        await service.refresh_plugins()
    assert kernel.runtime_registry.get("replaced").state is ExtensionLifecycleState.DISABLED
    assert kernel.loader.get_loaded_extensions()["replaced"] is instance
    instance._shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_and_disable_fail_while_plugin_executing(
    tmp_path: Path,
) -> None:
    import asyncio
    from types import SimpleNamespace

    _write_plugin(tmp_path, "running")
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    entered = asyncio.Event()
    release = asyncio.Event()

    class Executor:
        async def execute(self, request):
            entered.set()
            await release.wait()
            return "done"

    kernel.executor = Executor()
    request = SimpleNamespace(
        context=SimpleNamespace(request_id="running-turn"),
        plugin_id="running",
    )
    execution = asyncio.create_task(kernel.execute(request))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        with pytest.raises(RuntimeError, match="active executions"):
            await service.refresh_plugins()
        with pytest.raises(RuntimeError, match="active executions"):
            await service.disable_plugin("running")
        assert not (tmp_path / "running" / ".karen-manual-disabled").exists()
        assert kernel.runtime_registry.get("running").state is ExtensionLifecycleState.ENABLED
    finally:
        release.set()
        assert await execution == "done"
    await service.refresh_plugins()
    assert kernel.active_executions() == {}


@pytest.mark.asyncio
async def test_disable_retires_loaded_plugin_once_before_reenable(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _write_plugin(tmp_path, "switchable")
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    instance = SimpleNamespace(
        context=SimpleNamespace(extension_dir=tmp_path / "switchable"),
        is_shutdown=lambda: False,
        _shutdown=AsyncMock(),
    )
    kernel.loader._loaded_extensions["switchable"] = instance
    assert await service.disable_plugin("switchable")
    instance._shutdown.assert_awaited_once()
    assert kernel.loader.get_loaded_extensions() == {}
    assert kernel.runtime_registry.get("switchable").state is ExtensionLifecycleState.DISABLED
    assert await service.enable_plugin("switchable")
    assert kernel.runtime_registry.get("switchable").state is ExtensionLifecycleState.ENABLED
