"""Package uninstall uses canonical root, not shipped free_plugins files."""
from pathlib import Path
import pytest
from ai_karen_engine.services.plugin_service import PluginService

@pytest.mark.asyncio
async def test_uninstall_removes_package_and_refreshes_kernel(tmp_path: Path, monkeypatch):
    installed = tmp_path / "plugins"
    installed.mkdir()
    package = installed / "demo"
    package.mkdir()
    (package / "manifest.json").write_text('{"name":"demo"}')
    service = PluginService(installed, installed)
    calls = []
    class Kernel:
        _active = {}
        async def refresh(self):
            calls.append("refresh")
        def get_record(self, plugin_id):
            return None
    async def initialized():
        service.kernel = Kernel()
    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    result = await service.uninstall_plugin_package("demo")
    assert result == {"plugin_id":"demo","uninstalled":True}
    assert not package.exists()
    assert calls == ["refresh"]

@pytest.mark.asyncio
async def test_uninstall_rejects_unsafe_identifier(tmp_path: Path):
    service = PluginService(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        await service.uninstall_plugin_package("../escape")


@pytest.mark.asyncio
async def test_uninstall_refuses_active_execution(tmp_path: Path, monkeypatch):
    installed = tmp_path / "plugins"
    installed.mkdir()
    package = installed / "demo"
    package.mkdir()
    service = PluginService(installed, installed)
    class Kernel:
        _active = {"request-1": "demo"}
    async def initialized():
        service.kernel = Kernel()
    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    with pytest.raises(RuntimeError, match="active executions"):
        await service.uninstall_plugin_package("demo")
    assert package.is_dir()
    assert not (installed / ".plugin-install-demo.lock").exists()


@pytest.mark.asyncio
async def test_registry_rejection_restores_uninstalled_package(tmp_path: Path, monkeypatch):
    installed = tmp_path / "plugins"
    installed.mkdir()
    package = installed / "demo"
    package.mkdir()
    (package / "manifest.json").write_text('{"name":"demo"}')
    service = PluginService(installed, installed)
    class Kernel:
        _active = {}
        async def refresh(self):
            return 1
        def get_record(self, plugin_id):
            return object()
    async def initialized():
        service.kernel = Kernel()
    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    with pytest.raises(RuntimeError, match="remains in registry"):
        await service.uninstall_plugin_package("demo")
    assert (package / "manifest.json").is_file()
    assert not (installed / ".plugin-install-demo.lock").exists()
