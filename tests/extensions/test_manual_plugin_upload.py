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

    async def initialized():
        service.kernel = Kernel()

    monkeypatch.setattr(service, "_ensure_initialized", initialized)
    data = _archive({"manifest.json": json.dumps({"id": "demo"}), "handler.py": "pass"})
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
