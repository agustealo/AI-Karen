"""Consumer search should prioritize readable real evidence and accessible navigation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_general_query_does_not_inject_unrelated_intents():
    from ai_karen_engine.services.search.search_query_planner import SearchQueryPlanner

    assert SearchQueryPlanner().generate_queries("Jamaica History") == ["Jamaica History"]


def test_search_workspace_has_readable_default_and_adjustable_details():
    path = ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/ResultsWorkspace.tsx"
    ui = path.read_text(encoding="utf-8")
    assert "useState(false)" in ui
    assert "Details width" in ui
    assert "setShowDetails" in ui
    assert "min-h-[50vh]" in ui
    assert "No search evidence retrieved" in ui


def test_sidebar_scroll_and_source_first_results():
    sidebar = (ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/ui/sidebar.tsx").read_text(encoding="utf-8")
    results = (ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/Panels.tsx").read_text(encoding="utf-8")
    assert "overflow-y-auto overscroll-contain" in sidebar
    assert 'aria-label="Relevant search passages"' in results
    assert "results.slice(0, 5)" in results


def test_public_search_response_does_not_embed_unbounded_crawler_payloads():
    source = (ROOT / "src/ai_karen_engine/services/tooling/internet_capability_service.py").read_text(encoding="utf-8")
    assert '"crawl_results": list(crawl_results)' not in source
    assert '"processed_chunks": list(processed_chunks)' not in source
    assert '"full_content": bounded_markdown' in source
    assert '"markdown": bounded_markdown' in source
    assert '"content": content[:1500]' in source
