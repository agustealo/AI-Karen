from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.services.plugin_service import PluginService


def _write_plugin(
    root: Path, plugin_id: str = "alpha-plugin",
    *, dependencies: tuple[str, ...] = (),
) -> None:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "handler.py").write_text(
        "class MainExtension:\n    pass\n", encoding="utf-8"
    )
    (plugin_dir / "plugin_manifest.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "1.0.0",
                "display_name": "Alpha Plugin",
                "description": "Refresh-state fixture",
                "dependencies": {"plugins": list(dependencies)},
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


@pytest.mark.asyncio
async def test_disabled_required_plugin_blocks_default_and_explicit_dependent_enable(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "foundation")
    _write_plugin(tmp_path, "consumer", dependencies=("foundation",))
    (tmp_path / "foundation" / ".karen-manual-disabled").write_text(
        "explicitly disabled", encoding="utf-8",
    )
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    for plugin_id in ("foundation", "consumer"):
        registration = kernel.runtime_registry.get(plugin_id)
        assert registration is not None
        assert registration.state is ExtensionLifecycleState.DISABLED

    with pytest.raises(ValueError, match="Required plugin dependencies"):
        await service.enable_plugin("consumer")
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.DISABLED

    assert await service.enable_plugin("foundation")
    assert await service.enable_plugin("consumer")
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.ENABLED
    await service.refresh_plugins()
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.ENABLED


@pytest.mark.asyncio
async def test_disabling_required_plugin_refuses_without_mutating_durable_gate(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "foundation")
    _write_plugin(tmp_path, "consumer", dependencies=("foundation",))
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None

    with pytest.raises(ValueError, match="required by an enabled dependent"):
        await service.disable_plugin("foundation")
    assert not (tmp_path / "foundation" / ".karen-manual-disabled").exists()
    assert kernel.runtime_registry.get("foundation").state is ExtensionLifecycleState.ENABLED
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.ENABLED


@pytest.mark.asyncio
async def test_transitive_disabled_dependency_fails_closed_during_refresh(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "foundation")
    _write_plugin(tmp_path, "middle", dependencies=("foundation",))
    _write_plugin(tmp_path, "consumer", dependencies=("middle",))
    (tmp_path / "foundation" / ".karen-manual-disabled").write_text(
        "explicitly disabled", encoding="utf-8",
    )
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    assert all(
        kernel.runtime_registry.get(plugin_id).state is ExtensionLifecycleState.DISABLED
        for plugin_id in ("foundation", "middle", "consumer")
    )
    with pytest.raises(ValueError, match="middle"):
        await service.enable_plugin("consumer")

    assert await service.enable_plugin("foundation")
    assert await service.enable_plugin("middle")
    assert await service.enable_plugin("consumer")
    with pytest.raises(ValueError, match="enabled dependent"):
        await service.disable_plugin("foundation")
    await service.refresh_plugins()
    assert all(
        kernel.runtime_registry.get(plugin_id).state is ExtensionLifecycleState.ENABLED
        for plugin_id in ("foundation", "middle", "consumer")
    )
