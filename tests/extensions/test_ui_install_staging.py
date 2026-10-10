"""UI packages must be complete before their published path appears."""

from __future__ import annotations

from types import SimpleNamespace

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def _service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    service.validator.validate_plugin_structure = lambda *_: SimpleNamespace(is_valid=True)
    service.manifest_enforcer.validate_plugin_manifests = lambda *_: {}
    return service


def test_failed_staging_does_not_publish_partial_package(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"absent.tsx"}')
    result = service.install_ui("demo", "integration")
    assert result.error_code == "STAGING_FAILED"
    assert not (tmp_path / "repo/demo").exists()
    assert "demo" not in service.installations
    assert not list((tmp_path / "repo").glob(".install-*"))


def test_valid_package_publishes_complete_entry(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (source / "demo.tsx").write_text("export default function Demo() { return null; }")
    result = service.install_ui("demo", "integration")
    assert result.status == ui_installer.UIInstallationStatus.SUCCESS
    assert (tmp_path / "repo/demo/demo.tsx").is_file()
    assert "demo" in service.installations
    assert not list((tmp_path / "repo").glob(".install-*"))


def test_post_publish_validation_failure_removes_untracked_package(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (source / "demo.tsx").write_text("export default null")
    original_checksum = service._calculate_checksum
    calls = []

    def fail_after_publish(path):
        calls.append(path)
        if path == tmp_path / "repo/demo":
            raise OSError("checksum failure after publish")
        return original_checksum(path)

    monkeypatch.setattr(service, "_calculate_checksum", fail_after_publish)
    result = service.install_ui("demo", "integration")
    assert result.error_code == "POST_PUBLISH_VALIDATION_FAILED"
    assert len(calls) == 2
    assert not (tmp_path / "repo/demo").exists()
    assert "demo" not in service.installations


def test_staged_ui_refuses_symlinked_nested_assets(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/demo"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (source / "demo.tsx").write_text("export default null")
    other = tmp_path / "external.tsx"
    other.write_text("external")
    # The package source is checked for links before copying. Inject a linked
    # asset into staging immediately before the final staged integrity check.
    original = service._calculate_checksum

    def check_staged(path):
        if path.name.startswith(".install-"):
            (path / "linked.tsx").symlink_to(other)
        return original(path)

    monkeypatch.setattr(service, "_calculate_checksum", check_staged)
    result = service.install_ui("demo", "integration")
    assert result.error_code == "STAGING_FAILED"
    assert not (tmp_path / "repo/demo").exists()
    assert "demo" not in service.installations
