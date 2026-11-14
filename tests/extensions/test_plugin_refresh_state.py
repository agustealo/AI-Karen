from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.services.plugin_service import PluginService


def _write_plugin(
    root: Path, plugin_id: str = "alpha-plugin",
    *, dependencies: tuple[str, ...] = (), default_enabled: bool = True,
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
                "rbac": {"default_enabled": default_enabled},
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
async def test_dependency_recovery_restores_default_enabled_dependent_after_refresh(
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
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.DISABLED
    # A dependency-derived block is not the same as an explicit user disable.
    # The dependent may return to its declared default once its prerequisite
    # is explicitly enabled and a fresh catalog projection is accepted.
    assert "consumer" not in kernel._disabled
    assert await service.enable_plugin("foundation")
    await service.refresh_plugins()
    assert kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.ENABLED
    assert "consumer" not in kernel._disabled


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


@pytest.mark.asyncio
async def test_uploaded_plugin_remains_untrusted_under_builtin_root_after_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_plugin(tmp_path, "uploaded-demo")
    package = tmp_path / "uploaded-demo"
    (package / ".karen-upload-origin").write_text(
        "origin=manual_upload;trust=untrusted\n", encoding="utf-8"
    )
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    monkeypatch.setattr(kernel, "_is_builtin_root", lambda: True)

    await service.refresh_plugins()
    registration = kernel.runtime_registry.get("uploaded-demo")
    assert registration is not None
    assert registration.manifest.trust_tier.value == "untrusted"
    assert registration.state is ExtensionLifecycleState.DISABLED

    # Removing a disable marker cannot silently promote the upload to a
    # first-party plugin, nor make it executable after a restart/refresh.
    (package / ".karen-manual-disabled").unlink(missing_ok=True)
    await service.refresh_plugins()
    registration = kernel.runtime_registry.get("uploaded-demo")
    assert registration is not None
    assert registration.manifest.trust_tier.value == "untrusted"
    assert registration.state is ExtensionLifecycleState.DISABLED
    with pytest.raises(ValueError, match="isolated runtime"):
        await service.enable_plugin("uploaded-demo")


@pytest.mark.asyncio
async def test_explicit_enable_of_default_disabled_plugin_survives_restart(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "opt-in", default_enabled=False)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()

    registry = service.kernel.runtime_registry
    assert registry.get("opt-in").state is ExtensionLifecycleState.DISABLED
    assert await service.enable_plugin("opt-in") is True
    marker = tmp_path / "opt-in" / ".karen-manual-enabled"
    assert marker.read_text(encoding="utf-8") == "enabled\n"

    await service.refresh_plugins()
    assert service.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.ENABLED

    # A new process has no in-memory lifecycle state from the previous kernel.
    restarted = PluginService(tmp_path, tmp_path)
    await restarted.initialize()
    assert restarted.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.ENABLED
    assert marker.is_file()


@pytest.mark.asyncio
async def test_explicit_disable_replaces_persisted_opt_in_across_restart(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "opt-in", default_enabled=False)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    assert await service.enable_plugin("opt-in") is True
    assert await service.disable_plugin("opt-in") is True

    assert not (tmp_path / "opt-in" / ".karen-manual-enabled").exists()
    assert (tmp_path / "opt-in" / ".karen-manual-disabled").is_file()

    await service.refresh_plugins()
    assert service.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.DISABLED
    restarted = PluginService(tmp_path, tmp_path)
    await restarted.initialize()
    assert restarted.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.DISABLED

    assert await restarted.enable_plugin("opt-in")
    assert (tmp_path / "opt-in" / ".karen-manual-enabled").is_file()
    assert not (tmp_path / "opt-in" / ".karen-manual-disabled").exists()


@pytest.mark.asyncio
async def test_corrupted_explicit_enable_marker_cannot_override_default_disabled(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "opt-in", default_enabled=False)
    marker = tmp_path / "opt-in" / ".karen-manual-enabled"
    marker.write_text("not-enabled\n", encoding="utf-8")

    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    assert service.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.DISABLED
    with pytest.raises(ValueError, match="Invalid plugin enabled-state marker"):
        await service.enable_plugin("opt-in")


@pytest.mark.asyncio
async def test_explicit_enable_dependency_graph_remains_consistent_on_refresh(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "foundation", default_enabled=False)
    _write_plugin(tmp_path, "consumer", dependencies=("foundation",), default_enabled=True)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    assert service.kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.DISABLED

    assert await service.enable_plugin("foundation") is True
    await service.refresh_plugins()
    assert service.kernel.runtime_registry.get("foundation").state is ExtensionLifecycleState.ENABLED
    assert service.kernel.runtime_registry.get("consumer").state is ExtensionLifecycleState.ENABLED

    with pytest.raises(ValueError, match="required by an enabled dependent"):
        await service.disable_plugin("foundation")
    assert (tmp_path / "foundation" / ".karen-manual-enabled").is_file()


@pytest.mark.asyncio
async def test_failed_durable_opt_in_rolls_back_without_claiming_enable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_plugin(tmp_path, "opt-in", default_enabled=False)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel

    def fail_write(_plugin_id: str) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(kernel, "_persist_explicit_enable", fail_write)
    with pytest.raises(OSError, match="storage unavailable"):
        await service.enable_plugin("opt-in")

    assert kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.DISABLED
    assert not (tmp_path / "opt-in" / ".karen-manual-enabled").exists()
    restarted = PluginService(tmp_path, tmp_path)
    await restarted.initialize()
    assert restarted.kernel.runtime_registry.get("opt-in").state is ExtensionLifecycleState.DISABLED
