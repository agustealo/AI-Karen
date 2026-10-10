"""Startup discovery may not trust manifest-controlled filesystem links."""

from __future__ import annotations

import json

import pytest

from ai_karen_engine.extensions.platform.core.registry import ui_installer


@pytest.mark.parametrize("entry", ["../../outside.tsx", "/tmp/outside.tsx"])
def test_discovery_rejects_manifest_entry_escape(tmp_path, entry):
    root = tmp_path / "repo"
    package = root / "example"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps({"entry_file": entry}))
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(root), backup_dir=str(tmp_path / "backups")
    )
    assert "example" not in service.installations


def test_discovery_rejects_symlinked_plugin_directory(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "manifest.json").write_text('{"entry_file":"plugin.tsx"}')
    (outside / "plugin.tsx").write_text("export default null")
    (root / "example").symlink_to(outside, target_is_directory=True)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(root), backup_dir=str(tmp_path / "backups")
    )
    assert "example" not in service.installations


def test_discovery_rejects_symlinked_entry(tmp_path):
    root = tmp_path / "repo"
    package = root / "example"
    package.mkdir(parents=True)
    outside = tmp_path / "outside.tsx"
    outside.write_text("outside")
    (package / "manifest.json").write_text('{"entry_file":"example.tsx"}')
    (package / "example.tsx").symlink_to(outside)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(root), backup_dir=str(tmp_path / "backups")
    )
    assert "example" not in service.installations
