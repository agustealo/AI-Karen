"""Search UI must not display a failed search as a fetched excerpt."""

from pathlib import Path


def test_empty_retrieval_renders_truthful_state():
    root = Path(__file__).resolve().parents[2]
    ui = (
        root
        / "src/ai_karen_engine/extensions/plugins/intelligent-search/ui/components/ResultsWorkspace.tsx"
    ).read_text(encoding="utf-8")
    assert "No search evidence retrieved" in ui
    assert "No sources found" in ui
    assert "Search could not be completed" in ui
    assert "response?.summary ||" not in ui.split("const featuredPreview =", 1)[1].split("const featuredHref", 1)[0]
