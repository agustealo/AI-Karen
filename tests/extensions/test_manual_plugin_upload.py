"""Explicit ZIP upload installs locally without activation or overwrite."""

import io
import json
import zipfile

import pytest

from ai_karen_engine.services.plugin_service import PluginService


def _archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_upload_requires_explicit_enable(tmp_path, monkeypatch):
    service = PluginService(tmp_path, tmp_path)
    called = []

    async def no_enable(name):
        called.append(name)
        return 1

    class Kernel:
        refresh_with_new_plugin_disabled = staticmethod(no_enable)
        get_record = staticmethod(lambda plugin_id: {"manifest": object(), "error_message": None})

    async def initialized():
        service.kernel = Kernel()

    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    data = _archive({"manifest.json": json.dumps({"id": "demo", "name": "demo", "version": "1.0.0", "display_name": "Demo", "description": "Test plugin", "author": "Tests", "license": "MIT", "category": "integration"}), "handler.py": "pass"})
    result = await service.install_uploaded_archive("demo", data)
    assert result == {"plugin_id": "demo", "installed": True, "enabled": False}
    assert called == ["demo"]
    assert (tmp_path / "demo/handler.py").exists()
    assert (tmp_path / "demo/.karen-manual-disabled").is_file()
    with pytest.raises(FileExistsError):
        await service.install_uploaded_archive("demo", data)


@pytest.mark.asyncio
async def test_zip_slip_refused_without_publication(tmp_path):
    service = PluginService(tmp_path, tmp_path)
    data = _archive({"../escape": "bad", "manifest.json": "{}"})
    with pytest.raises(ValueError):
        await service.install_uploaded_archive("demo", data)
    assert not (tmp_path / "demo").exists()


@pytest.mark.asyncio
async def test_wrong_manifest_id_refused(tmp_path):
    service = PluginService(tmp_path, tmp_path)
    data = _archive({"manifest.json": json.dumps({"id": "other"})})
    with pytest.raises(ValueError):
        await service.install_uploaded_archive("demo", data)
    assert not (tmp_path / "demo").exists()


@pytest.mark.asyncio
async def test_registry_rejection_rolls_back_published_package(tmp_path, monkeypatch):
    service = PluginService(tmp_path, tmp_path)

    class Kernel:
        async def refresh_with_new_plugin_disabled(self, name):
            return 1

        def get_record(self, name):
            return None

    async def initialized():
        service.kernel = Kernel()

    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    manifest = {
        "id": "demo", "name": "demo", "version": "1.0.0",
        "display_name": "Demo", "description": "Test plugin",
        "author": "Tests", "license": "MIT", "category": "integration",
    }
    with pytest.raises(ValueError, match="runtime registry validation"):
        await service.install_uploaded_archive("demo", _archive({"manifest.json": json.dumps(manifest)}))
    assert not (tmp_path / "demo").exists()


@pytest.mark.asyncio
async def test_concurrent_install_lock_never_overwrites(tmp_path):
    service = PluginService(tmp_path, tmp_path)
    manifest = {
        "id": "demo", "name": "demo", "version": "1.0.0",
        "display_name": "Demo", "description": "Test plugin",
        "author": "Tests", "license": "MIT", "category": "integration",
    }
    lock = tmp_path / ".plugin-install-demo.lock"
    lock.write_text("active")
    with pytest.raises(FileExistsError):
        await service.install_uploaded_archive(
            "demo", _archive({"manifest.json": json.dumps(manifest)})
        )
    assert not (tmp_path / "demo").exists()
    assert lock.read_text() == "active"


@pytest.mark.asyncio
async def test_lock_held_through_registry_validation_and_released(tmp_path, monkeypatch):
    service = PluginService(tmp_path, tmp_path)
    observed = []

    class Kernel:
        async def refresh_with_new_plugin_disabled(self, name):
            observed.append((tmp_path / ".plugin-install-demo.lock").exists())
            return 1

        def get_record(self, name):
            return {"manifest": object(), "error_message": None}

    async def initialized():
        service.kernel = Kernel()

    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    manifest = {
        "id": "demo", "name": "demo", "version": "1.0.0",
        "display_name": "Demo", "description": "Test plugin",
        "author": "Tests", "license": "MIT", "category": "integration",
    }
    await service.install_uploaded_archive("demo", _archive({"manifest.json": json.dumps(manifest)}))
    assert observed == [True]
    assert not (tmp_path / ".plugin-install-demo.lock").exists()
