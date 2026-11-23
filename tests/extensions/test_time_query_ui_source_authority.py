"""Time Query frontend has one canonical source and a governed publication path."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest,
    find_backend_manifest_file,
)
from ai_karen_engine.extensions.platform.core.registry.manifest_enforcer import (
    ManifestStandardsEnforcer,
    ManifestValidationSeverity,
)
from ai_karen_engine.extensions.platform.core.registry.ui_installer import (
    UIInstallerService,
)
from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
    UIMaterializationPipeline,
)


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/time-query"
PUBLISHED = ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/time-query"
CANONICAL_ASSETS = (
    "TimeQueryPage.tsx",
    "components/AlarmEditor.tsx",
    "components/AlarmList.tsx",
    "components/AlarmPanel.tsx",
    "components/CurrentTimePanel.tsx",
    "components/DiagnosticsPanel.tsx",
    "components/MultiClockGrid.tsx",
    "components/StopwatchPanel.tsx",
    "components/TimezoneConversionPanel.tsx",
    "hooks/useAlarms.ts",
    "hooks/useStopwatch.ts",
    "hooks/useTimePayload.ts",
    "hooks/useTimeQuery.ts",
    "hooks/useWorldClocks.ts",
    "services/timeQueryApi.ts",
    "types/index.ts",
)


class _TimeQueryRegistry:
    def __init__(self, plugin_dir: Path, *, valid: bool = True) -> None:
        self._plugin_dir = plugin_dir
        self._valid = valid

    async def list_all_extensions(self):
        return [
            SimpleNamespace(
                name="time-query",
                display_name="Time Query",
                version="0.2.0",
                status=SimpleNamespace(value="enabled"),
                capabilities={"provides_ui": True},
            )
        ]

    def get_metadata(self, plugin_id: str):
        if plugin_id != "time-query":
            return None
        return SimpleNamespace(
            is_valid=self._valid,
            validation_errors=[] if self._valid else ["denied"],
            directory=self._plugin_dir,
            manifest_path=self._plugin_dir / "plugin_manifest.json",
            display_name="Time Query",
            version="0.2.0",
            category="productivity",
            capabilities={"provides_ui": True},
        )


def _pipeline(tmp_path: Path, source: Path, *, valid: bool = True):
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "published"),
    )
    pipeline.registry = _TimeQueryRegistry(source, valid=valid)
    return pipeline


def test_time_query_backend_and_gui_declarations_are_separate() -> None:
    backend = PLUGIN / "plugin_manifest.json"
    frontend = PLUGIN / "manifest.json"
    backend_data = json.loads(backend.read_text(encoding="utf-8"))
    gui_data = json.loads(frontend.read_text(encoding="utf-8"))

    assert "entry" not in backend_data
    assert find_backend_manifest_file(PLUGIN) == backend
    assert ExtensionManifest.from_dict(backend_data).name == "time-query"
    assert gui_data["plugin_id"] == "time-query"
    assert gui_data["entry"]["entry_file"] == "TimeQueryPage.tsx"
    issues = ManifestStandardsEnforcer().validate_gui_manifest(frontend)
    assert not [
        issue for issue in issues
        if issue.severity is ManifestValidationSeverity.ERROR
    ]
    page = PLUGIN / "ui" / gui_data["entry"]["entry_file"]
    assert page.is_file() and not page.is_symlink()
    content = page.read_text(encoding="utf-8")
    assert "usePluginExtension('time-query')" in content
    assert "new TimeQueryApi(api)" in content


def test_active_time_query_frontend_has_no_shadow_source_drift() -> None:
    for relative in CANONICAL_ASSETS:
        source = PLUGIN / "ui" / relative
        published = PUBLISHED / relative
        assert source.is_file(), f"missing canonical Time Query source: {relative}"
        assert not source.is_symlink(), f"linked canonical asset: {relative}"
        assert published.is_file(), f"missing tracked published asset: {relative}"
        assert source.read_bytes() == published.read_bytes(), (
            f"Time Query source/published drift: {relative}"
        )


@pytest.mark.asyncio
async def test_clean_governed_time_query_publication_and_restart(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, PLUGIN)
    discovered = await pipeline.discover_ui_plugins()
    assert len(discovered) == 1
    assert discovered[0]["registry_validated"] is True
    assert discovered[0]["has_component"] is True
    assert discovered[0]["component_path"] == str(PLUGIN / "ui/TimeQueryPage.tsx")
    assert discovered[0]["gui_manifest_path"] == str(PLUGIN / "manifest.json")

    result = await pipeline.materialize_all()
    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["import_map"]["time-query"] == (
        "@/plugin_repo/time-query/TimeQueryPage"
    )
    output = tmp_path / "published/time-query"
    assert (output / "manifest.json").read_bytes() == (
        PLUGIN / "manifest.json"
    ).read_bytes()
    for relative in CANONICAL_ASSETS:
        assert (output / relative).read_bytes() == (
            PLUGIN / "ui" / relative
        ).read_bytes(), relative

    installer = UIInstallerService(
        plugins_repo_root=str(tmp_path / "published"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert "time-query" in installer.installations
    assert installer.installations["time-query"].entry_file == (
        output / "TimeQueryPage.tsx"
    )


@pytest.mark.asyncio
async def test_unvalidated_catalog_never_publishes_time_query(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, PLUGIN, valid=False)
    assert await pipeline.discover_ui_plugins() == []
    assert not (tmp_path / "published/time-query").exists()


@pytest.mark.asyncio
async def test_malformed_gui_entry_never_publishes_time_query(tmp_path: Path) -> None:
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin_manifest.json").write_bytes(
        (PLUGIN / "plugin_manifest.json").read_bytes()
    )
    gui = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    gui["entry"]["entry_file"] = "../outside.tsx"
    (source / "manifest.json").write_text(json.dumps(gui), encoding="utf-8")
    pipeline = _pipeline(tmp_path, source)
    assert await pipeline.discover_ui_plugins() == []
    assert not (tmp_path / "published/time-query").exists()
