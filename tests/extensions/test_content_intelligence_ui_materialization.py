"""Prove the actual governed UI materializer handles the shared Content Intelligence.

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
    / "src/ai_karen_engine/extensions/plugins/content-intelligence"
)


class _AuthorizedRegistry:
    def __init__(self, metadata):
        self.metadata = metadata

    async def list_all_extensions(self):
        return [
            SimpleNamespace(
                name="content-intelligence",
                display_name="Content Intelligence",
                version="0.2.0",
                status=SimpleNamespace(value="active"),
                capabilities={"provides_ui": True},
            )
        ]

    def get_metadata(self, plugin_id):
        return self.metadata if plugin_id == "content-intelligence" else None


@pytest.mark.asyncio
async def test_content_intelligence_materializes_from_validated_canonical_manifest(tmp_path):
    manifest_path = PLUGIN / "plugin_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["capabilities"]["provides_ui"] is True
    assert manifest["ui"]["entry_file"] == "ContentIntelligencePage.tsx"

    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=PLUGIN,
        manifest_path=manifest_path,
        display_name="Content Intelligence",
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
    assert discovered[0]["component_path"].endswith("/ui/ContentIntelligencePage.tsx")

    result = await pipeline.materialize_plugin(discovered[0])
    output = tmp_path / "plugin-repo/content-intelligence"
    assert (output / "ContentIntelligencePage.tsx").read_bytes() == (
        PLUGIN / "ui/ContentIntelligencePage.tsx"
    ).read_bytes()
    published = json.loads((output / "manifest.json").read_text())
    assert discovered[0]["gui_manifest_path"] == str(PLUGIN / "manifest.json")
    assert published == json.loads((PLUGIN / "manifest.json").read_text())
    assert published["name"] == "content-intelligence"
    assert published["entry"]["entry_file"] == "ContentIntelligencePage.tsx"
    assert (output / published["entry"]["entry_file"]).is_file()
    assert result["plugin_id"] == "content-intelligence"


@pytest.mark.asyncio
async def test_content_intelligence_ui_not_exposed_when_registry_metadata_invalid(tmp_path):
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
    assert not (tmp_path / "plugin-repo/content-intelligence").exists()


def test_materialized_content_intelligence_is_discovered_by_real_ui_installer(tmp_path):
    """The published manifest must load through the canonical installer, not just copy."""
    from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
        UIInstallerService,
    )

    target = tmp_path / "plugin-repo" / "content-intelligence"
    target.mkdir(parents=True)
    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / manifest["entry"]["entry_file"]).write_bytes(
        (PLUGIN / "ui" / manifest["entry"]["entry_file"]).read_bytes()
    )
    installer = UIInstallerService(
        plugins_repo_root=str(tmp_path / "plugin-repo"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert "content-intelligence" in installer.installations
    assert installer.installations["content-intelligence"].entry_file == (
        target / "ContentIntelligencePage.tsx"
    )


@pytest.mark.asyncio
async def test_materialize_all_reports_only_successfully_materialized_imports(tmp_path):
    metadata = SimpleNamespace(
        is_valid=True,
        validation_errors=[],
        directory=PLUGIN,
        manifest_path=PLUGIN / "plugin_manifest.json",
        display_name="Content Intelligence",
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
    assert result["import_map"]["content-intelligence"] == (
        "@/plugin_repo/content-intelligence/ContentIntelligencePage"
    )
    assert (tmp_path / "plugin-repo/content-intelligence/ContentIntelligencePage.tsx").is_file()


