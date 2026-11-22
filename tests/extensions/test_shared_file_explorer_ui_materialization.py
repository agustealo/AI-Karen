"""Prove the actual governed UI materializer handles the shared File Explorer.

Test uses real plugin files and the production materialization implementation,
with a minimal registry double as the authorization/discovery boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
    UIMaterializationPipeline,
)


PLUGIN = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/extensions/plugins/file-explorer"
)


class _AuthorizedRegistry:
    def __init__(self, metadata):
        self.metadata = metadata

    async def list_all_extensions(self):
        return [
            SimpleNamespace(
                name="file-explorer",
                display_name="File Explorer",
                version="0.2.0",
                status=SimpleNamespace(value="active"),
                capabilities={"provides_ui": True},
            )
        ]

    def get_metadata(self, plugin_id):
        return self.metadata if plugin_id == "file-explorer" else None


@pytest.mark.asyncio
async def test_file_explorer_materializes_from_validated_canonical_manifest(tmp_path):
    manifest_path = PLUGIN / "plugin_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["capabilities"]["provides_ui"] is True
    assert manifest["ui"]["entry_file"] == "FileExplorerPage.tsx"

    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=PLUGIN,
        manifest_path=manifest_path,
        display_name="File Explorer",
        version="0.2.0",
        category="integration",
        capabilities={"provides_ui": True},
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "ui-artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin-repo"),
    )
    pipeline.registry = _AuthorizedRegistry(metadata)
    discovered = await pipeline.discover_ui_plugins()
    assert len(discovered) == 1
    assert discovered[0]["registry_validated"] is True
    assert discovered[0]["has_component"] is True
    assert discovered[0]["component_path"].endswith("/ui/FileExplorerPage.tsx")

    result = await pipeline.materialize_plugin(discovered[0])
    output = tmp_path / "plugin-repo/file-explorer"
    assert (output / "FileExplorerPage.tsx").read_bytes() == (
        PLUGIN / "ui/FileExplorerPage.tsx"
    ).read_bytes()
    published = json.loads((output / "manifest.json").read_text())
    assert published["name"] == "file-explorer"
    assert published["entry"]["entry_file"] == "FileExplorerPage.tsx"
    assert (output / published["entry"]["entry_file"]).is_file()
    assert result["plugin_id"] == "file-explorer"


@pytest.mark.asyncio
async def test_file_explorer_ui_not_exposed_when_registry_metadata_invalid(tmp_path):
    metadata = SimpleNamespace(
        is_valid=False,
        validation_errors=["denied"],
        directory=PLUGIN,
        manifest_path=PLUGIN / "plugin_manifest.json",
        capabilities={"provides_ui": True},
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "ui-artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin-repo"),
    )
    pipeline.registry = _AuthorizedRegistry(metadata)
    assert await pipeline.discover_ui_plugins() == []
    assert not (tmp_path / "plugin-repo/file-explorer").exists()


def test_materialized_file_explorer_is_discovered_by_real_ui_installer(tmp_path):
    """The published manifest must load through the canonical installer, not just copy."""
    from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
        UIInstallerService,
    )

    target = tmp_path / "plugin-repo" / "file-explorer"
    target.mkdir(parents=True)
    manifest = json.loads((PLUGIN / "plugin_manifest.json").read_text(encoding="utf-8"))
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / manifest["entry"]["entry_file"]).write_bytes(
        (PLUGIN / "ui" / manifest["entry"]["entry_file"]).read_bytes()
    )
    installer = UIInstallerService.__new__(UIInstallerService)
    installer.plugins_repo_root = tmp_path / "plugin-repo"
    installer.backup_dir = tmp_path / "backups"
    installer.installations = {}
    installer._load_installations()
    assert "file-explorer" in installer.installations
    assert installer.installations["file-explorer"].entry_file == (
        target / "FileExplorerPage.tsx"
    )


@pytest.mark.asyncio
async def test_materialize_all_reports_only_successfully_materialized_imports(tmp_path):
    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=PLUGIN,
        manifest_path=PLUGIN / "plugin_manifest.json",
        display_name="File Explorer",
        version="0.2.0",
        category="integration",
        capabilities={"provides_ui": True},
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin-repo"),
    )
    pipeline.registry = _AuthorizedRegistry(metadata)
    result = await pipeline.materialize_all()
    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["import_map"]["file-explorer"] == (
        "@/plugin_repo/file-explorer/FileExplorerPage"
    )
    assert (tmp_path / "plugin-repo/file-explorer/FileExplorerPage.tsx").is_file()


@pytest.mark.asyncio
async def test_failed_ui_copy_cannot_claim_importer_or_success(tmp_path, monkeypatch):
    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=PLUGIN,
        manifest_path=PLUGIN / "plugin_manifest.json",
        display_name="File Explorer",
        version="0.2.0",
        category="integration",
        capabilities={"provides_ui": True},
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin-repo"),
    )
    pipeline.registry = _AuthorizedRegistry(metadata)

    async def failed_copy(plugin_ui):
        return False

    monkeypatch.setattr(pipeline, "_materialize_ui_source", failed_copy)
    result = await pipeline.materialize_all()
    assert result["status"] == "degraded"
    assert result["errors"][0]["plugin_id"] == "file-explorer"
    assert result["import_map"] == {}
    assert not (tmp_path / "plugin-repo/file-explorer/FileExplorerPage.tsx").exists()


@pytest.mark.asyncio
async def test_missing_validated_ui_entry_fails_closed_without_false_success(tmp_path):
    """A registry-valid provides_ui plugin still needs an actual component."""
    plugin_dir = tmp_path / "missing-ui"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin_manifest.json"
    manifest_path.write_bytes((PLUGIN / "plugin_manifest.json").read_bytes())
    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=plugin_dir,
        manifest_path=manifest_path,
        display_name="File Explorer",
        version="0.2.0",
        category="integration",
        capabilities={"provides_ui": True},
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin-repo"),
    )
    pipeline.registry = _AuthorizedRegistry(metadata)
    discovered = await pipeline.discover_ui_plugins()
    assert len(discovered) == 1
    assert discovered[0]["registry_validated"] is True
    assert discovered[0]["has_component"] is False

    result = await pipeline.materialize_all()
    assert result["status"] == "degraded"
    assert result["plugins_processed"] == 1
    assert result["errors"][0]["plugin_id"] == "file-explorer"
    assert "entry component missing" in result["errors"][0]["error"]
    assert result["import_map"] == {}
    assert not (tmp_path / "plugin-repo/file-explorer").exists()


@pytest.mark.asyncio
async def test_linked_source_asset_does_not_materialize_or_copy_private_content(tmp_path):
    """A validated registry record does not make linked source bytes safe."""
    import os

    source = tmp_path / "plugin"
    ui = source / "ui"
    ui.mkdir(parents=True)
    original = PLUGIN / "plugin_manifest.json"
    (source / "plugin_manifest.json").write_bytes(original.read_bytes())
    (ui / "FileExplorerPage.tsx").write_bytes(
        (PLUGIN / "ui/FileExplorerPage.tsx").read_bytes()
    )
    private = tmp_path / "private.tsx"
    private.write_text("private content", encoding="utf-8")
    os.symlink(private, ui / "leak.tsx")

    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "published"),
    )
    authorized = {
        "plugin_id": "file-explorer",
        "registry_validated": True,
        "has_component": True,
        "component_path": str(ui / "FileExplorerPage.tsx"),
        "plugin_dir": str(source),
        "manifest_path": str(source / "plugin_manifest.json"),
        "ui_config": {"source_path": "ui", "entry_file": "FileExplorerPage.tsx"},
        "icons": [],
        "menu_config": [],
    }
    assert await pipeline._materialize_ui_source(authorized) is False
    assert not (tmp_path / "published/file-explorer").exists()
    assert private.read_text(encoding="utf-8") == "private content"


@pytest.mark.asyncio
async def test_linked_published_target_never_receives_materialized_assets(tmp_path):
    """Existing links in the target are not overwritten or followed."""
    import os

    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.tsx"
    sentinel.write_text("unchanged", encoding="utf-8")
    output = tmp_path / "published"
    output.mkdir()
    os.symlink(external, output / "file-explorer")
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(output),
    )
    authorized = {
        "plugin_id": "file-explorer",
        "registry_validated": True,
        "has_component": True,
        "component_path": str(PLUGIN / "ui/FileExplorerPage.tsx"),
        "plugin_dir": str(PLUGIN),
        "manifest_path": str(PLUGIN / "plugin_manifest.json"),
        "ui_config": {"source_path": "ui", "entry_file": "FileExplorerPage.tsx"},
        "icons": [],
        "menu_config": [],
    }
    assert await pipeline._materialize_ui_source(authorized) is False
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert not (external / "FileExplorerPage.tsx").exists()


@pytest.mark.asyncio
async def test_ui_source_path_cannot_escape_validated_plugin_root(tmp_path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin_manifest.json").write_bytes(
        (PLUGIN / "plugin_manifest.json").read_bytes()
    )
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "published"),
    )
    authorized = {
        "plugin_id": "file-explorer",
        "registry_validated": True,
        "has_component": True,
        "component_path": str(PLUGIN / "ui/FileExplorerPage.tsx"),
        "plugin_dir": str(source),
        "manifest_path": str(source / "plugin_manifest.json"),
        "ui_config": {"source_path": "../"},
        "icons": [],
        "menu_config": [],
    }
    assert await pipeline._materialize_ui_source(authorized) is False
    assert not (tmp_path / "published/file-explorer").exists()
