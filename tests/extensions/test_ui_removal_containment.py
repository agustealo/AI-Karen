"""Removal must never trust a stale or malicious installer inventory path."""

from __future__ import annotations

import pytest

from ai_karen_engine.extensions.platform.core.registry import ui_installer


@pytest.mark.parametrize("relative_target", ["../outside", "other-plugin"])
def test_remove_refuses_inventory_target_redirect(tmp_path, relative_target):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "preserve.txt"
    sentinel.write_text("keep", encoding="utf-8")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    service.installations["example"] = ui_installer.UIPackageInfo(
        plugin_id="example",
        source_path=tmp_path / "source",
        target_path=repo / relative_target,
        manifest_path=repo / relative_target / "manifest.json",
        entry_file=repo / relative_target / "example.tsx",
        checksum="", size_bytes=0,
    )
    result = service.remove_ui("example")
    assert result.error_code == "UNSAFE_REMOVAL_TARGET"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert "example" in service.installations


def test_remove_refuses_symlink_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "preserve.txt").write_text("keep", encoding="utf-8")
    (repo / "example").symlink_to(outside, target_is_directory=True)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    service.installations["example"] = ui_installer.UIPackageInfo(
        plugin_id="example", source_path=tmp_path / "source",
        target_path=repo / "example",
        manifest_path=repo / "example/manifest.json",
        entry_file=repo / "example/example.tsx",
        checksum="", size_bytes=0,
    )
    result = service.remove_ui("example")
    assert result.error_code == "UNSAFE_REMOVAL_TARGET"
    assert (outside / "preserve.txt").read_text(encoding="utf-8") == "keep"
