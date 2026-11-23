"""GUI manifests are presentation metadata, not executable plugin grants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest,
    find_backend_manifest_file,
)
from ai_karen_engine.extensions.platform.core.registry.discovery import (
    ExtensionDiscoveryService,
)
from ai_karen_engine.extensions.platform.core.registry.manifest_enforcer import (
    ManifestStandardsEnforcer,
    ManifestValidationSeverity,
)
from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
    UIInstallerService,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel


def _backend_data(name: str = "example") -> dict:
    return {
        "name": name,
        "version": "1.0.0",
        "display_name": "Example",
        "description": "Test backend extension",
        "author": "KAREN",
        "license": "MIT",
        "category": "integration",
        "entrypoint": "handler:MainExtension",
        "capabilities": {"provides_api": True},
    }


def _gui_data(name: str = "example") -> dict:
    return {
        "id": name,
        "name": name,
        "plugin_id": name,
        "gui_manifest_version": "1.0",
        "version": "1.0.0",
        "category": "integration",
        "display_name": "Example",
        "entry": {"id": "main", "default": True, "entry_file": "ExamplePage.tsx"},
    }


@pytest.mark.asyncio
async def test_gui_only_manifest_never_becomes_executable_or_grants_permissions(
    tmp_path: Path,
) -> None:
    package = tmp_path / "example"
    package.mkdir()
    gui = _gui_data()
    # Even maliciously supplied backend-looking declarations do not change the
    # authority of a versioned GUI manifest.
    gui.update(
        entrypoint="handler:MainExtension",
        permissions={"memory_write": True, "system_config_write": True},
        rbac={"allowed_roles": ["admin"], "default_enabled": True},
    )
    (package / "manifest.json").write_text(json.dumps(gui), encoding="utf-8")
    (package / "handler.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")

    assert find_backend_manifest_file(package) is None
    discovery = ExtensionDiscoveryService(tmp_path)
    assert await discovery.discover_extensions() == {}
    kernel = PluginKernel(tmp_path)
    assert await kernel.refresh() == 0
    assert kernel.runtime_registry.get("example") is None
    assert kernel.get_record("example") is None


@pytest.mark.asyncio
async def test_backend_legacy_filename_remains_discoverable(tmp_path: Path) -> None:
    package = tmp_path / "example"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps(_backend_data()), encoding="utf-8"
    )

    assert find_backend_manifest_file(package) == package / "manifest.json"
    registry = ExtensionDiscoveryService(tmp_path)
    result = await registry.discover_extensions()
    assert result["example"].manifest_path == package / "manifest.json"
    assert result["example"].is_valid


@pytest.mark.parametrize("field,value", [
    ("entry", {"id": "inject", "entry_file": "Injected.tsx"}),
    ("entry_file", "Injected.tsx"),
    ("plugin_id", "example"),
    ("gui_manifest_version", "1.0"),
])
def test_executable_manifest_rejects_gui_metadata(field: str, value: object) -> None:
    data = _backend_data()
    data[field] = value
    with pytest.raises(ValueError, match="GUI entry metadata"):
        ExtensionManifest.from_dict(data)


@pytest.mark.parametrize("entry", [
    "ExamplePage.tsx",
    {},
    {"id": "main", "default": "yes", "entry_file": "ExamplePage.tsx"},
    {"id": "main", "entry_file": "../outside.tsx"},
    {"id": "main", "entry_file": "/tmp/outside.tsx"},
    {"id": "main", "entry_file": "ExamplePage.py"},
    {"id": "main", "entry_file": ["ExamplePage.tsx"]},
    {"id": "main", "entry_file": "ExamplePage.tsx", "permission": "admin"},
])
def test_gui_validator_rejects_malformed_entries(
    tmp_path: Path, entry: object
) -> None:
    gui = _gui_data()
    gui["entry"] = entry
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(gui), encoding="utf-8")

    issues = ManifestStandardsEnforcer().validate_gui_manifest(path)
    assert any(i.severity is ManifestValidationSeverity.ERROR for i in issues)


def test_valid_gui_entry_survives_separate_gui_validation(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_gui_data()), encoding="utf-8")
    issues = ManifestStandardsEnforcer().validate_gui_manifest(path)
    assert not [i for i in issues if i.severity is ManifestValidationSeverity.ERROR]


def test_invalid_gui_entry_is_not_rediscovered_as_installed_ui(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    package = root / "example"
    package.mkdir(parents=True)
    gui = _gui_data()
    gui["entry"]["default"] = "yes"
    (package / "manifest.json").write_text(json.dumps(gui), encoding="utf-8")
    (package / "ExamplePage.tsx").write_text("export default null", encoding="utf-8")

    service = UIInstallerService(
        plugins_repo_root=str(root),
        backup_dir=str(tmp_path / "backups"),
    )
    assert "example" not in service.installations


def test_unversioned_gui_entry_keeps_restart_compatibility(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    package = root / "example"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps({"entry": {"entry_file": "ExamplePage.tsx"}}),
        encoding="utf-8",
    )
    (package / "ExamplePage.tsx").write_text(
        "export default null", encoding="utf-8"
    )

    service = UIInstallerService(
        plugins_repo_root=str(root),
        backup_dir=str(tmp_path / "backups"),
    )
    assert "example" in service.installations
    assert not service.installations["example"].checksum


def test_unversioned_gui_entry_rejects_invalid_types(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    package = root / "example"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps({"entry": {"entry_file": "ExamplePage.tsx", "default": "yes"}}),
        encoding="utf-8",
    )
    (package / "ExamplePage.tsx").write_text(
        "export default null", encoding="utf-8"
    )

    service = UIInstallerService(
        plugins_repo_root=str(root),
        backup_dir=str(tmp_path / "backups"),
    )
    assert "example" not in service.installations


def test_first_party_gui_and_runtime_manifests_keep_distinct_ownership() -> None:
    root = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins"
    )
    enforcer = ManifestStandardsEnforcer()

    for name in ("file-explorer", "intelligent-search", "time-query"):
        directory = root / name
        backend = directory / "plugin_manifest.json"
        gui = directory / "manifest.json"
        backend_data = json.loads(backend.read_text(encoding="utf-8"))
        assert "entry" not in backend_data
        assert find_backend_manifest_file(directory) == backend
        assert ExtensionManifest.from_dict(backend_data).name == name

        gui_data = json.loads(gui.read_text(encoding="utf-8"))
        assert gui_data["entry"]["entry_file"].endswith(".tsx")
        issues = enforcer.validate_gui_manifest(gui)
        assert not [
            issue for issue in issues
            if issue.severity is ManifestValidationSeverity.ERROR
        ]
