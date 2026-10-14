"""Consumer search source payload must distinguish complete articles from previews."""

from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
)


def _article(paragraphs: int = 3) -> dict:
    section = (
        "Jamaican history includes Indigenous communities, colonial rule, "
        "enslavement, emancipation, and independence in 1962. "
        "These events had lasting consequences for society and culture."
    )
    return {
        "url": "https://example.org/history-of-jamaica",
        "title": "History of Jamaica",
        "markdown": "\n\n".join(
            f"## Period {index}\n\n{section}" for index in range(paragraphs)
        ),
        "metadata": {"title": "History of Jamaica"},
    }


def test_complete_source_preserves_later_sections_not_just_first_passage():
    service = InternetCapabilityService()
    result = _article(4)
    sources = service._build_sources([result])
    assert len(sources) == 1
    source = sources[0]
    assert source["article_complete"] is True
    assert source["full_content"] == result["markdown"]
    assert source["markdown"] == result["markdown"]
    assert "Period 3" in source["full_content"]
    assert source["article_preview"] is None
    assert source["article_char_count"] == len(result["markdown"])


def test_oversized_article_is_explicitly_partial_not_falsely_full():
    service = InternetCapabilityService()
    result = _article(500)
    sources = service._build_sources([result])
    assert len(sources) == 1
    source = sources[0]
    assert source["article_complete"] is False
    assert source["full_content"] is None
    assert source["markdown"] is None
    assert len(source["article_preview"]) == 32000
    assert source["article_char_count"] == len(result["markdown"])
