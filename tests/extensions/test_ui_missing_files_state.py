"""A damaged plugin must not disappear from UI installation inventory."""

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_missing_entry_retains_broken_installation_evidence(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "demo"
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    entry = pkg / "demo.tsx"
    entry.write_text("valid")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backup")
    )
    assert "demo" in service.installations
    entry.unlink()
    state = service.get_ui_state("demo")
    assert state["state"] == "error"
    assert state["status"] == "validation_failed"
    assert state["error_code"] == "FILES_MISSING"
    assert "demo" in service.installations
    assert (pkg / "manifest.json").exists()


def test_missing_package_does_not_remove_inventory(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "demo"
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"entry_file":"demo.tsx"}')
    (pkg / "demo.tsx").write_text("valid")
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo), backup_dir=str(tmp_path / "backup")
    )
    import shutil
    shutil.rmtree(pkg)
    assert service.get_ui_state("demo")["error_code"] == "FILES_MISSING"
    assert "demo" in service.installations
