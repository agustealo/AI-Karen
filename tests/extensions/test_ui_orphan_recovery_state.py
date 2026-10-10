"""Interrupted package publication must not be reported as uninstalled."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_published_orphan_requires_recovery(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    orphan = repo / "demo"
    orphan.mkdir()
    (orphan / "manifest.json").write_text("{}", encoding="utf-8")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    state = service.get_ui_state("demo")
    assert state["state"] == "error"
    assert state["status"] == "validation_failed"
    assert state["error_code"] == "INCOMPLETE_INSTALLATION"
    assert orphan.is_dir()


def test_orphan_integrity_record_requires_recovery(tmp_path):
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    service._save_baseline("demo", "a" * 64)
    state = service.get_ui_state("demo")
    assert state["error_code"] == "INCOMPLETE_INSTALLATION"
    assert state["status"] == "validation_failed"


def test_absent_plugin_remains_uninstalled(tmp_path):
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert service.get_ui_state("demo")["state"] == "not_installed"
    assert service.get_ui_state("../escape")["error_code"] == "INVALID_PLUGIN_ID"
