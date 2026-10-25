"""Guard against automatic submission of untrusted research excerpts."""

from pathlib import Path


def test_search_source_chat_handoff_requires_explicit_user_submission():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/Panels.tsx"
    )
    source = path.read_text(encoding="utf-8")
    handoff = source.split("const sendToChat =", 1)[1].split(
        "/**", 1
    )[0]

    assert "karen:inject-message" in handoff
    assert "role: 'user'" in handoff
    assert "autoSubmit: false" in handoff
    assert "autoSubmit: true" not in handoff
    assert "Untrusted excerpt:" in handoff
