"""Intelligent Search first-party UI has one canonical, testable source owner.

These checks are not browser/production-host acceptance. They verify real
repository bytes, the governed materializer, and the existing UI installer.
"""

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
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/intelligent-search"
SOURCE = PLUGIN / "ui"
PUBLISHED = ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search"
RELEASE = ROOT / "free_plugins/essential/intelligent-search"
IMPORT_MAP = (
    ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin-import-map.generated.ts"
)


class _Registry:
    """Only supplies an explicitly governed catalog record, not authorization."""

    def __init__(
        self, directory: Path, *, valid: bool = True, status: str = "active"
    ) -> None:
        self.directory = directory
        self.valid = valid
        self.status = status

    async def list_all_extensions(self):
        return [
            SimpleNamespace(
                name="intelligent-search",
                display_name="Intelligent Search",
                version="2.0.0",
                status=SimpleNamespace(value=self.status),
                capabilities={"provides_ui": True, "provides_api": True},
            )
        ]

    def get_metadata(self, plugin_id: str):
        if plugin_id != "intelligent-search":
            return None
        return SimpleNamespace(
            is_valid=self.valid,
            validation_errors=[] if self.valid else ["catalog denied"],
            directory=self.directory,
            manifest_path=self.directory / "plugin_manifest.json",
            display_name="Intelligent Search",
            version="2.0.0",
            category="integration",
            capabilities={"provides_ui": True, "provides_api": True},
        )


def _pipeline(tmp_path: Path, directory: Path, *, valid=True, status="active"):
    pipeline = UIMaterializationPipeline(
        extensions_dir=str(tmp_path / "extensions"),
        artifacts_dir=str(tmp_path / "artifacts"),
        plugins_ui_dir=str(tmp_path / "published"),
    )
    pipeline.registry = _Registry(directory, valid=valid, status=status)
    return pipeline


def _assets(root: Path) -> dict[str, bytes]:
    assert root.is_dir()
    result = {}
    for path in sorted(root.rglob("*")):
        assert not path.is_symlink(), f"linked search UI source: {path}"
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def test_manifest_authorities_do_not_conflate_frontend_with_backend() -> None:
    backend_file = PLUGIN / "plugin_manifest.json"
    gui_file = PLUGIN / "manifest.json"
    backend = json.loads(backend_file.read_text(encoding="utf-8"))
    gui = json.loads(gui_file.read_text(encoding="utf-8"))
    assert "entry" not in backend
    assert find_backend_manifest_file(PLUGIN) == backend_file
    assert ExtensionManifest.from_dict(backend).name == "intelligent-search"
    assert backend["rbac"]["default_enabled"] is True
    assert gui["id"] == gui["plugin_id"] == backend["name"]
    assert gui["entry"]["entry_file"] == "IntelligentSearchPage.tsx"
    assert not [
        issue for issue in ManifestStandardsEnforcer().validate_gui_manifest(gui_file)
        if issue.severity is ManifestValidationSeverity.ERROR
    ]


def test_no_shadow_source_or_stale_release_mirror() -> None:
    canonical_assets = _assets(SOURCE)
    assert "IntelligentSearchPage.tsx" in canonical_assets
    assert "hooks/useIntelligentSearch.ts" in canonical_assets
    assert "services/IntelligentSearchApi.ts" in canonical_assets
    assert "hooks/useWebSearch.ts" not in canonical_assets
    assert "services/webSearchApi.ts" not in canonical_assets

    published_assets = _assets(PUBLISHED)
    assert published_assets.pop("manifest.json") == (
        PLUGIN / "manifest.json"
    ).read_bytes()
    assert canonical_assets == published_assets
    assert canonical_assets == _assets(RELEASE / "ui")
    assert (RELEASE / "manifest.json").read_bytes() == (
        PLUGIN / "manifest.json"
    ).read_bytes()


def test_generated_frontend_map_resolves_all_first_party_entries_once() -> None:
    import_map = IMPORT_MAP.read_text(encoding="utf-8")
    for name, entry in (
        ("file-explorer", "FileExplorerPage"),
        ("intelligent-search", "IntelligentSearchPage"),
        ("time-query", "TimeQueryPage"),
    ):
        expected = (
            f'"{name}": () => '
            f'import("@/plugin_repo/{name}/{entry}")'
        )
        assert import_map.count(expected) == 1
        assert (ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo"
                / name / f"{entry}.tsx").is_file()


@pytest.mark.asyncio
async def test_clean_materialization_and_real_installer_restart(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, PLUGIN)
    discovered = await pipeline.discover_ui_plugins()
    assert len(discovered) == 1
    ui = discovered[0]
    assert ui["registry_validated"] is True
    assert ui["has_component"] is True
    assert ui["component_path"] == str(SOURCE / "IntelligentSearchPage.tsx")
    assert ui["gui_manifest_path"] == str(PLUGIN / "manifest.json")

    result = await pipeline.materialize_all()
    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["import_map"]["intelligent-search"] == (
        "@/plugin_repo/intelligent-search/IntelligentSearchPage"
    )
    output = tmp_path / "published/intelligent-search"
    assert (output / "manifest.json").read_bytes() == (
        PLUGIN / "manifest.json"
    ).read_bytes()
    assert _assets(output) == _assets(PUBLISHED)

    installer = UIInstallerService(
        plugins_repo_root=str(tmp_path / "published"),
        backup_dir=str(tmp_path / "backups"),
    )
    assert installer.installations["intelligent-search"].entry_file == (
        output / "IntelligentSearchPage.tsx"
    )


@pytest.mark.asyncio
async def test_denied_registry_record_cannot_publish_ui(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, PLUGIN, valid=False)
    assert await pipeline.discover_ui_plugins() == []
    assert not (tmp_path / "published/intelligent-search").exists()


@pytest.mark.asyncio
async def test_disabled_catalog_state_is_not_fabricated_as_active(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, PLUGIN, status="disabled")
    discovered = await pipeline.discover_ui_plugins()
    assert len(discovered) == 1
    assert discovered[0]["status"] == "disabled"
    assert discovered[0]["registry_validated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("plugin_id", "other"),
        ("category", "security"),
        ("entry", {"id": "main", "entry_file": "../outside.tsx"}),
    ],
)
async def test_modified_gui_manifest_cannot_publish(
    tmp_path: Path, field: str, value: object
) -> None:
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "plugin_manifest.json").write_bytes(
        (PLUGIN / "plugin_manifest.json").read_bytes()
    )
    gui = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    gui[field] = value
    (directory / "manifest.json").write_text(
        json.dumps(gui), encoding="utf-8"
    )
    pipeline = _pipeline(tmp_path, directory)
    assert await pipeline.discover_ui_plugins() == []
    assert not (tmp_path / "published/intelligent-search").exists()
