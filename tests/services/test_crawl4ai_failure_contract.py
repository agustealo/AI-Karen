"""Crawl4AI unavailable state must produce a structured result, never crash."""

from ai_karen_engine.integrations.web.crawl4ai_integration import Crawl4AIIntegration


def test_missing_dependency_failure_constructs_valid_result_without_content():
    # No browser or network required. Exercise the exact production failure factory.
    crawler = object.__new__(Crawl4AIIntegration)
    failure = crawler._failure_result(
        "https://example.org/article",
        started=0.0,
        error="Crawl4AI dependency unavailable",
        failure_code="dependency_unavailable",
    )
    assert failure.success is False
    assert failure.extracted_content is None
    assert failure.markdown == ""
    assert failure.error == "Crawl4AI dependency unavailable"
    assert failure.failure_code == "dependency_unavailable"
    assert failure.to_dict()["extracted_content"] is None
