"""The UI install checksum must survive restarts without trusting changed bytes."""

from __future__ import annotations

import json

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_durable_baseline_survives_installer_restart(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "sample"
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"entry_file": "sample.tsx"}')
    entry = pkg / "sample.tsx"
    entry.write_text("original")
    backups = tmp_path / "backups"
    installer = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(backups)
    )
    original_hash = installer._calculate_checksum(pkg)
    installer._save_baseline("sample", original_hash)
    recovered = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(backups)
    )
    assert recovered.installations["sample"].checksum == original_hash
    assert recovered.get_ui_state("sample")["status"] == "success"
    entry.write_text("modified after install")
    restarted = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(backups)
    )
    assert restarted.get_ui_state("sample")["status"] == "validation_failed"


def test_missing_or_malformed_baseline_is_not_trusted(tmp_path):
    installer = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"), backup_dir=str(tmp_path / "backups")
    )
    assert installer._load_baseline("sample") == ""
    path = installer._baseline_path("sample")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"plugin_id": "another", "sha256": "a" * 64}))
    assert installer._load_baseline("sample") == ""
