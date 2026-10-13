"""A failed crawl must not masquerade as a retrieved page or citation."""

from types import SimpleNamespace

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


def test_failed_crawls_excluded_from_normalized_evidence():
    service = object.__new__(InternetCapabilityService)
    failed = {
        "url": "https://example.org/no-content",
        "success": False,
        "markdown": "",
        "error": "dependency unavailable",
    }
    good = {
        "url": "https://example.org/real",
        "success": True,
        "markdown": "Verified fetched text.",
    }
    failed_object = SimpleNamespace(**failed)
    normalized = service._normalize_crawl_results([failed, failed_object, good])
    assert normalized == [good]


def test_successful_object_crawl_remains_retrievable():
    service = object.__new__(InternetCapabilityService)
    good = SimpleNamespace(
        url="https://example.org/real",
        success=True,
        markdown="Fetched text",
        text="Fetched text",
    )
    normalized = service._normalize_crawl_results([good])
    assert len(normalized) == 1
    assert normalized[0]["url"] == good.url
    assert normalized[0]["success"] is True
