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
    assert json.loads((output / "manifest.json").read_text())["name"] == "file-explorer"
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
