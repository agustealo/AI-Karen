"""Search preview may only claim actually retrieved evidence."""

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


def test_summary_uses_real_attributed_passages_not_crawl_statistics():
    service = object.__new__(InternetCapabilityService)
    answer = service._build_summary(
        query="Jamaica history",
        mode="general",
        sources=[{"url": "https://example.org/history", "domain": "example.org"}],
        results=[{
            "url": "https://example.org/history",
            "snippet": "Jamaica gained independence in 1962.",
        }],
        execution_time_ms=123,
        degraded=False,
        warnings=[],
    )
    assert "Jamaica gained independence in 1962" in answer
    assert "https://example.org/history" in answer
    assert "not a generated answer" in answer
    assert "123ms" not in answer


def test_discovery_only_results_do_not_become_fetched_answer():
    service = object.__new__(InternetCapabilityService)
    answer = service._build_summary(
        query="Jamaica history",
        mode="general",
        sources=[{"url": "https://example.org/history", "evidence_level": "search_snippet"}],
        results=[],
        execution_time_ms=123,
        degraded=True,
        warnings=["Crawler unavailable"],
    )
    assert "no fetched passages" in answer
    assert "Crawler unavailable" not in answer
