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
