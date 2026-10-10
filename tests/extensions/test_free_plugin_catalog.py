"""Manual free-plugin installation is opt-in and non-destructive."""

import json

import pytest

from scripts import manage_free_plugins as catalog


def test_catalog_lists_essential_packages():
    for name in ("time-query", "intelligent-search"):
        assert (catalog.CATALOG / "essential" / name / "manifest.json").is_file()


def test_manual_install_does_not_replace_existing_package(tmp_path, monkeypatch):
    source = tmp_path / "free_plugins/essential/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(json.dumps({"id": "demo"}))
    monkeypatch.setattr(catalog, "CATALOG", tmp_path / "free_plugins")
    target_root = tmp_path / "installed"
    target = catalog.install("essential", "demo", target_root)
    assert (target / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        catalog.install("essential", "demo", target_root)


def test_reject_invalid_plugin_id_and_linked_source(tmp_path, monkeypatch):
    source = tmp_path / "free_plugins/essential/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text("{}")
    (source / "unsafe").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(catalog, "CATALOG", tmp_path / "free_plugins")
    with pytest.raises(ValueError):
        catalog.install("essential", "../demo", tmp_path / "installed")
    with pytest.raises(ValueError):
        catalog.install("essential", "demo", tmp_path / "installed")
    assert not (tmp_path / "installed/demo").exists()
