"""Restart discovery must not certify a fresh checksum as original truth."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_restart_does_not_trust_mutated_ui_package(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "sample"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        '{"entry": {"entry_file": "sample.tsx"}}', encoding="utf-8"
    )
    (package / "sample.tsx").write_text("changed after prior install", encoding="utf-8")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backups")
    )
    assert "sample" in service.installations
    assert not service.installations["sample"].checksum
    status = service.get_ui_state("sample")
    assert status["status"] == "validation_failed"
    result = service.validate_ui_package("sample")
    assert result.error_code == "INTEGRITY_BASELINE_UNAVAILABLE"
    assert package.is_dir()
