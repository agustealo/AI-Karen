"""Search UI must not display a failed search as a fetched excerpt."""

from pathlib import Path


def test_empty_retrieval_renders_truthful_state():
    root = Path(__file__).resolve().parents[2]
    ui = (
        root
        / "src/ai_karen_engine/extensions/plugins/intelligent-search/ui/components/ResultsWorkspace.tsx"
    ).read_text(encoding="utf-8")
    assert "No search evidence retrieved" in ui
    assert "No result or citation has been verified." in ui
    assert "Search failed: no evidence" in ui
    assert "response?.summary ||" not in ui.split("const featuredPreview =", 1)[1].split("const featuredHref", 1)[0]
