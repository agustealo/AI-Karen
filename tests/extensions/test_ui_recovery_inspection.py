"""Recovery inspection must not repair, approve or delete unknown UI bytes."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def _service(tmp_path):
    return ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )


def test_inspection_preserves_unregistered_package(tmp_path):
    service = _service(tmp_path)
    target = tmp_path / "repo" / "demo"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("preserve")
    result = service.inspect_recovery("demo")
    assert result["classification"] == "unregistered_package"
    assert result["action"] == "manual_review"
    assert result["can_auto_repair"] is False
    assert sentinel.read_text() == "preserve"


def test_inspection_identifies_orphan_checksum_without_mutation(tmp_path):
    service = _service(tmp_path)
    service._save_baseline("demo", "a" * 64)
    result = service.inspect_recovery("demo")
    assert result["classification"] == "orphan_integrity_record"
    assert result["can_auto_repair"] is False
    assert service._baseline_path("demo").exists()


def test_inspection_blocks_invalid_identifiers(tmp_path):
    service = _service(tmp_path)
    result = service.inspect_recovery("../escape")
    assert result["classification"] == "invalid_identifier"
    assert result["action"] == "none"
