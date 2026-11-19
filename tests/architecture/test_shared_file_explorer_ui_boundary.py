"""Guard shared explorer UI ownership and avoid invented live availability."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/file-explorer"


def test_gui_declared_on_shared_extension_only():
    gui = json.loads((PLUGIN / "manifest.json").read_text())
    assert gui["entry"]["entry_file"] == "FileExplorerPage.tsx"
    assert gui["id"] == gui["plugin_id"] == "file-explorer"
    assert gui["capabilities"]["provides_ui"] is True


def test_explorer_requires_host_inventory_and_has_no_direct_source_io():
    ui = (PLUGIN / "ui/FileExplorerPage.tsx").read_text()
    assert "authorized = false" in ui
    assert "onSelect?.(references)" in ui
    assert "No authorized file inventory" in ui
    assert "fetch(" not in ui
    assert "localStorage" not in ui
    assert "input type=\"file\"" not in ui
    assert "File access is checked again" in ui


def test_content_intelligence_does_not_own_an_explorer_component():
    intelligence = ROOT / "src/ai_karen_engine/extensions/plugins/content-intelligence"
    assert not (intelligence / "ui/FileExplorerPage.tsx").exists()


def test_canonical_manifest_registers_materializable_shared_ui():
    manifest = json.loads((PLUGIN / "plugin_manifest.json").read_text())
    assert manifest["capabilities"]["provides_ui"] is True
    assert manifest["ui"]["source_path"] == "ui"
    assert manifest["ui"]["entry_file"] == "FileExplorerPage.tsx"
    assert manifest["entry"]["entry_file"] == manifest["ui"]["entry_file"]
    assert (PLUGIN / "ui" / manifest["ui"]["entry_file"]).is_file()
    assert manifest["ui"]["menu"][0]["zone"] == "sidebar.plugins"


def test_authorized_inventory_failure_preserves_error_and_retry():
    ui = (PLUGIN / "ui/FileExplorerPage.tsx").read_text(encoding="utf-8")
    assert "authorized && error &&" in ui
    assert "authorized && onRefresh &&" in ui
    assert 'onClick={refresh}>Refresh</button>' in ui


def test_pagination_is_host_driven_and_invalid_evidence_fails_closed():
    ui = (PLUGIN / "ui/FileExplorerPage.tsx").read_text(encoding="utf-8")
    assert "onNextPage?: (cursor: string) => void" in ui
    assert "hasMore?: boolean" in ui
    assert "nextCursor?: string | null" in ui
    assert "pageEvidenceValid" in ui
    assert "!pageEvidenceValid" in ui
    assert "onNextPage?.(nextCursor)" in ui
    assert "disabled={loading || Boolean(error) || !pageEvidenceValid}" in ui
    assert "Boolean(error) || !pageEvidenceValid" in ui
    assert "Invalid host pagination evidence." in ui
    assert "key={props.pageKey ?? 'initial'}" in ui
    assert "clearSelections();" in ui
    assert "onSelect?.([])" in ui
    assert "fetch(" not in ui
    assert "localStorage" not in ui
