"""Hashing must bind file names, contents, and reject links."""

from __future__ import annotations

import pytest

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_checksum_changes_when_paths_change_but_bytes_do_not(tmp_path):
    repo = tmp_path / "repo"
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    package = repo / "example"
    package.mkdir()
    (package / "first.tsx").write_bytes(b"same content")
    first = service._calculate_checksum(package)
    (package / "first.tsx").rename(package / "second.tsx")
    second = service._calculate_checksum(package)
    assert first != second
    assert second == service._calculate_checksum(package)


def test_checksum_rejects_symlink_file_and_directory(tmp_path):
    repo = tmp_path / "repo"
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    package = repo / "example"
    package.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.tsx").write_bytes(b"payload")
    (package / "linked.tsx").symlink_to(outside / "payload.tsx")
    with pytest.raises(ValueError, match="Unsafe"):
        service._calculate_checksum(package)
    (package / "linked.tsx").unlink()
    (package / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Linked"):
        service._calculate_checksum(package)
