"""Release proof for the packaged File Explorer UI, not runtime authorization.

The static frontend build can only bundle artifacts included in its build context.
The canonical installer/materializer owns source copying; release artifacts must
remain byte-identical to its governed UI source and GUI manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/ai_karen_engine/extensions/plugins/file-explorer"
PACKAGE = ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/file-explorer"
IMPORT_MAP = (
    ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin-import-map.generated.ts"
)


def test_file_explorer_release_bundle_matches_canonical_governed_source():
    assert (PACKAGE / "FileExplorerPage.tsx").read_bytes() == (
        SOURCE / "ui/FileExplorerPage.tsx"
    ).read_bytes()
    assert (PACKAGE / "manifest.json").read_bytes() == (
        SOURCE / "manifest.json"
    ).read_bytes()


def test_file_explorer_release_bundle_has_valid_entry_without_runtime_grants():
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "file-explorer"
    assert manifest["plugin_id"] == "file-explorer"
    assert manifest["capabilities"]["provides_ui"] is True
    assert manifest["capabilities"]["prompt_first"] is True
    assert manifest["rbac"]["default_enabled"] is False
    entry = manifest["entry"]["entry_file"]
    assert entry == "FileExplorerPage.tsx"
    assert (PACKAGE / entry).is_file()


def test_build_map_includes_canonical_file_explorer_entry_without_fallback():
    import_map = IMPORT_MAP.read_text(encoding="utf-8")
    importer = (
        '"file-explorer": () => '
        'import("@/plugin_repo/file-explorer/FileExplorerPage")'
    )
    assert import_map.count(importer) == 1
    assert "src/ai_karen_engine/extensions/plugins/file-explorer" not in import_map
