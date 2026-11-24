"""Search retrieval status is not a model answer or a stack of excerpts."""

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


def test_fetched_research_status_never_masquerades_as_model_answer():
    service = object.__new__(InternetCapabilityService)
    status = service._build_summary(
        query="Jamaica history",
        mode="general",
        sources=[{
            "url": "https://example.org/history",
            "domain": "example.org",
            "evidence_level": "fetched_page",
        }],
        results=[{
            "url": "https://example.org/history",
            "snippet": "Jamaica gained independence in 1962.",
        }],
        execution_time_ms=123,
        degraded=False,
        warnings=[],
    )
    assert "1 fetched source" in status
    assert "has not generated an answer" in status
    assert "Jamaica gained independence" not in status
    assert "https://" not in status
    assert "123ms" not in status


def test_discovery_only_results_do_not_become_fetched_answer():
    service = object.__new__(InternetCapabilityService)
    status = service._build_summary(
        query="Jamaica history",
        mode="general",
        sources=[{
            "url": "https://example.org/history",
            "evidence_level": "search_snippet",
        }],
        results=[],
        execution_time_ms=123,
        degraded=True,
        warnings=["Crawler unavailable"],
    )
    assert "no fetched passages" in status
    assert "not a generated or verified answer" in status
    assert "Crawler unavailable" not in status
