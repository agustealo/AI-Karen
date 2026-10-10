"""Legacy bundled plugin packages recover only from matching canonical source."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_matching_bundled_ui_can_recover_missing_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (source / "demo.tsx").write_text("bundled version")
    package = tmp_path / "repo/demo"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (package / "demo.tsx").write_text("bundled version")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert service.installations["demo"].checksum == ""
    assert service._recover_bundled_integrity(service.installations["demo"])
    assert service._load_baseline("demo") == service._calculate_checksum(package)


def test_modified_bundled_ui_remains_unverified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (source / "demo.tsx").write_text("trusted")
    package = tmp_path / "repo/demo"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (package / "demo.tsx").write_text("tampered")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert not service._recover_bundled_integrity(service.installations["demo"])
    assert service._load_baseline("demo") == ""
    assert (package / "demo.tsx").read_text() == "tampered"
