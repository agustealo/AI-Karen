from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
    UIMaterializationPipeline,
)


class _EmptyRegistry:
    async def list_all_extensions(self):
        return []

    def list_extensions(self):
        return []

    def get_metadata(self, plugin_id: str):
        return None


class _Registry:
    def __init__(self, plugin, metadata):
        self.plugin = plugin
        self.metadata = metadata

    async def list_all_extensions(self):
        return [self.plugin]

    def list_extensions(self):
        return [self.plugin]

    def get_metadata(self, plugin_id: str):
        return self.metadata if plugin_id == self.plugin.name else None


def _pipeline(tmp_path: Path) -> UIMaterializationPipeline:
    return UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "plugin_repo"),
    )


@pytest.mark.asyncio
async def test_registry_unavailable_does_not_fallback_to_filesystem(tmp_path):
    plugin_dir = tmp_path / "extensions" / "rogue-plugin"
    ui_dir = plugin_dir / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "PluginPage.tsx").write_text("export default function Page() {}", encoding="utf-8")
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "rogue-plugin",
                "version": "9.9.9",
                "capabilities": {"provides_ui": True},
                "ui": {"source_path": "ui", "entry_file": "PluginPage.tsx"},
            }
        ),
        encoding="utf-8",
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _EmptyRegistry()

    assert await pipeline.discover_ui_plugins() == []


@pytest.mark.asyncio
async def test_invalid_registry_metadata_cannot_materialize_ui(tmp_path):
    plugin_dir = tmp_path / "extensions" / "weather-query"
    plugin_dir.mkdir(parents=True)
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "weather-query",
                "version": "1.0.0",
                "ui": {"source_path": "ui", "entry_file": "PluginPage.tsx"},
            }
        ),
        encoding="utf-8",
    )

    plugin = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="1.0.0",
        status=SimpleNamespace(value="active"),
        capabilities={"provides_ui": True},
    )
    metadata = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="1.0.0",
        category="information",
        capabilities={"provides_ui": True},
        directory=plugin_dir,
        manifest_path=manifest_path,
        is_valid=False,
        validation_errors=["invalid manifest"],
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _Registry(plugin, metadata)

    assert await pipeline.discover_ui_plugins() == []


@pytest.mark.asyncio
async def test_valid_registry_metadata_is_the_only_operational_truth(tmp_path):
    plugin_dir = tmp_path / "extensions" / "weather-query"
    ui_dir = plugin_dir / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "WeatherPage.tsx").write_text(
        "export default function WeatherPage() {}",
        encoding="utf-8",
    )
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "weather-query",
                "version": "2.3.0",
                "capabilities": {"provides_ui": True},
                "ui": {
                    "source_path": "ui",
                    "entry_file": "WeatherPage.tsx",
                    "menu": [{"placement": "tools"}],
                },
            }
        ),
        encoding="utf-8",
    )

    plugin = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="2.3.0",
        status=SimpleNamespace(value="inactive"),
        capabilities={"provides_ui": True},
    )
    metadata = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="2.3.0",
        category="information",
        capabilities={"provides_ui": True},
        directory=plugin_dir,
        manifest_path=manifest_path,
        is_valid=True,
        validation_errors=[],
    )

    pipeline = _pipeline(tmp_path)
    pipeline.registry = _Registry(plugin, metadata)

    discovered = await pipeline.discover_ui_plugins()

    assert len(discovered) == 1
    item = discovered[0]
    assert item["plugin_id"] == "weather-query"
    assert item["version"] == "2.3.0"
    assert item["status"] == "inactive"
    assert item["category"] == "information"
    assert item["registry_validated"] is True
    assert item["capabilities"] == {"provides_ui": True}
    assert item["has_component"] is True
    assert item["component_path"].endswith("WeatherPage.tsx")


def test_pipeline_contains_no_filesystem_authority_fallback():
    source = Path(__file__).parents[2] / "src" / "ai_karen_engine" / "extensions" / "platform" / "core" / "registry" / "ui_materialization.py"
    text = source.read_text(encoding="utf-8")

    forbidden = (
        "_discover_plugins_filesystem",
        '"status": "active"',
        '"version", "1.0.0"',
        "Assume active",
    )
    for token in forbidden:
        assert token not in text
