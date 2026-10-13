"""Search UI/runtime truth contracts must not imply unverified live results."""

from pathlib import Path

from ai_karen_engine.services.search.search_query_planner import SearchQueryPlanner


def test_query_expansion_does_not_force_specific_calendar_year():
    queries = SearchQueryPlanner().generate_queries("network protocols")
    assert queries
    assert queries[0] == "network protocols"
    assert not any("2026" in item for item in queries)


def test_dispatcher_status_no_longer_claims_unconditional_health():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py"
    )
    content = path.read_text(encoding="utf-8")
    assert '"status": "healthy"' not in content
    assert '"live_search_verified": False' in content


def test_search_ui_does_not_invent_crawler_as_provider():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins/intelligent-search/ui/components/ResultsWorkspace.tsx"
    )
    content = path.read_text(encoding="utf-8")
    assert "|| 'crawl4ai'" not in content
    assert "No sources retrieved" in content
