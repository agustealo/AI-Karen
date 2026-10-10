"""Adversarial regression tests for plugin UI installation path boundaries."""

from __future__ import annotations

from ai_karen_engine.extensions.platform.core.registry import ui_installer


def test_install_rejects_untracked_target_without_touching_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "src/ai_karen_engine/extensions/plugins/hello"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "repo/hello"
    destination.mkdir(parents=True)
    sentinel = destination / "retain.txt"
    sentinel.write_text("original", encoding="utf-8")

    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    result = service.install_ui("hello", "integration")
    assert result.error_code == "UNTRACKED_INSTALLATION"
    assert sentinel.read_text(encoding="utf-8") == "original"


def test_install_rejects_linked_plugin_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / "src/ai_karen_engine/extensions/plugins"
    root.mkdir(parents=True)
    (root / "hello").symlink_to(external, target_is_directory=True)

    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(tmp_path / "repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    result = service.install_ui("hello", "integration")
    assert result.error_code == "UNSAFE_SOURCE"
    assert not (tmp_path / "repo/hello").exists()


def test_install_rejects_linked_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "src/ai_karen_engine/extensions/plugins/hello"
    source.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello").symlink_to(external, target_is_directory=True)
    service = ui_installer.UIInstallerService(
        plugins_repo_root=str(repo),
        backup_dir=str(tmp_path / "backups"),
    )
    result = service.install_ui("hello", "integration")
    assert result.error_code == "UNSAFE_TARGET"
    assert (repo / "hello").is_symlink()
