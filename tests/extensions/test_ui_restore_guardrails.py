"""Restore must preserve any existing installed UI on repair failure."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_restore_keeps_installed_package_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = tmp_path / "repo" / "time-query"
    original.mkdir(parents=True)
    sentinel = original / "important.tsx"
    sentinel.write_text("working component", encoding="utf-8")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    service.installations["time-query"] = ui_installer.UIPackageInfo(
        plugin_id="time-query",
        source_path=tmp_path / "missing-source",
        target_path=original,
        manifest_path=original / "manifest.json",
        entry_file=sentinel,
        checksum="previous",
        size_bytes=sentinel.stat().st_size,
    )
    result = service.restore_ui("time-query", "integration")
    assert result.error_code == "REPAIR_REQUIRES_TRANSACTION"
    assert sentinel.read_text(encoding="utf-8") == "working component"
    assert "time-query" in service.installations


def test_restore_missing_plugin_returns_real_install_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    result = service.restore_ui("unknown-plugin", "integration")
    assert result.error_code == "PLUGIN_NOT_FOUND"
    assert "unknown-plugin" not in service.installations
