"""Search UI handoff must not masquerade as a generated assistant answer."""

from pathlib import Path

PANEL = (Path(__file__).resolve().parents[2] /
         "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/Panels.tsx")


def test_search_handoff_is_bounded_user_request():
    source = PANEL.read_text(encoding="utf-8")
    assert "Please explain this search evidence" in source
    assert "Untrusted excerpt" in source
    assert ".slice(0, 1200)" in source
    assert "karen:inject-message" in source
    assert "I found this information for you:" not in source


def test_source_url_guard_uses_parseable_typescript():
    source = PANEL.read_text(encoding="utf-8")
    assert "item.url.startsWith('https://')" in source
    assert "item.url.startsWith('http://')" in source
    assert r"/^https?:\\/\\//" not in source


SERVICE = (Path(__file__).resolve().parents[2] /
           "src/ai_karen_engine/services/tooling/internet_capability_service.py")
TYPES = (Path(__file__).resolve().parents[2] /
         "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/types/index.ts")
API = (Path(__file__).resolve().parents[2] /
       "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/services/IntelligentSearchApi.ts")


def test_source_provenance_has_a_single_backend_authority():
    backend = SERVICE.read_text(encoding="utf-8")
    types = TYPES.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    assert '"evidence_level": "fetched_page"' in backend
    assert '"evidence_level": "search_snippet"' in backend
    assert "evidence_level?: 'fetched_page' | 'search_snippet'" in types
    assert "source.evidence_level === 'fetched_page'" in panel
    assert "source.evidence_level === 'search_snippet'" in panel
    assert "Fetch status is not specified by the backend." in panel
    assert "return value;" in api
