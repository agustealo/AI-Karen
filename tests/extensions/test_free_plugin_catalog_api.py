"""Free plugin discovery is read-only and never promises installed state."""

import json

import pytest

from ai_karen_engine.api_routes.extensions import extensions as routes


@pytest.mark.asyncio
async def test_catalog_offers_packages_without_installing(tmp_path, monkeypatch):
    fake_file = tmp_path / "src/ai_karen_engine/api_routes/extensions/extensions.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    monkeypatch.setattr(routes, "__file__", str(fake_file))
    essential = tmp_path / "free_plugins/essential/time-query"
    essential.mkdir(parents=True)
    (essential / "manifest.json").write_text(
        json.dumps({"name": "Time Query", "version": "0.2.0"})
    )
    result = await routes.get_free_plugin_catalog(user={"id": "reader"})
    assert result["automatic_installation"] is False
    assert result["offerings"] == [{
        "plugin_id": "time-query",
        "category": "essential",
        "name": "Time Query",
        "version": "0.2.0",
        "description": "",
        "installation": "manual",
    }]


@pytest.mark.asyncio
async def test_catalog_skips_invalid_manifest(tmp_path, monkeypatch):
    fake_file = tmp_path / "src/ai_karen_engine/api_routes/extensions/extensions.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    monkeypatch.setattr(routes, "__file__", str(fake_file))
    folder = tmp_path / "free_plugins/essential/broken"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{not json")
    result = await routes.get_free_plugin_catalog(user={"id": "reader"})
    assert result["offerings"] == []
