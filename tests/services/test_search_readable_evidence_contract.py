"""Adversarial consumer evidence cleanup using observed Jamaica search clutter.

The crawler may return entire Markdown pages, but presentation/answer evidence
must not elevate menus, unrelated recommendations, or page references. No
browser, model, network, or privileged runtime context is needed for these tests.
"""

from ai_karen_engine.services.search.search_result_processor import (
    SearchResultProcessor,
)
from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
)

JAMAICA_PAGE = """
[Jump to content](https://en.wikipedia.org/wiki/History_of_Jamaica#bodyContent)

Main menu
Main menu
move to sidebar hide
Navigation
[Main page](https://en.wikipedia.org/wiki/Main_Page)

Related posts: ![Moko Jumbies and other unrelated recommendations]()
![The scheme that bankrupted a nation](https://example.org/other.jpg)
More recent articles about something other than Jamaica today.

Reader Interactions Leave a ReplyCancel reply Sidebar This Day In History
No Events World history recent posts include other stories irrelevant to Jamaica.

References [edit] 1. 1 2 3 4 "Jamaica" Archived 2019-04-20 at
the Wayback Machine Encyclopaedia Britannica. A long list of citations,
web citations, citation identifiers and other non-article material.

## History of Jamaica

Jamaica's Indigenous Taíno communities lived on the island before European
colonization. Spanish colonization began in 1494, and British rule followed in
1655. Enslaved Africans built communities, resisted plantation slavery, and
shaped Jamaican society through centuries of resistance and cultural change.

In 1962, Jamaica gained independence from the United Kingdom. The island
developed a modern Caribbean identity shaped by political independence,
language, art, music, and historical struggles.

External links [edit] Wikimedia Commons and other places where the reader
can find supplementary sources that are not part of the main article.
"""


def _result(markdown=JAMAICA_PAGE):
    return {
        "url": "https://en.wikipedia.org/wiki/History_of_Jamaica",
        "metadata": {"title": "History of Jamaica"},
        "markdown": markdown,
        "success": True,
    }


def test_article_evidence_rejects_navigation_recommendations_and_references():
    ranked = SearchResultProcessor().process([_result()], "history of Jamaica")
    joined = " ".join(item["content"] for item in ranked)
    assert "independence" in joined.lower()
    for phrase in (
        "Jump to content", "Reader Interactions", "Related posts",
        "External links", "Encyclopaedia Britannica",
    ):
        assert phrase.lower() not in joined.lower()


def test_reading_preview_is_readable_prose_without_raw_links_images_or_html():
    processor = SearchResultProcessor()
    preview = processor.readable_preview(_result(), limit=6000)
    assert "Taíno communities" in preview
    assert "independence" in preview
    assert "https://" not in preview
    assert "![" not in preview
    assert "<script" not in preview
    assert "Reader Interactions" not in preview


def test_raw_article_provenance_is_preserved_separately_from_readable_preview():
    service = InternetCapabilityService()
    sources = service._build_sources([_result()])
    assert len(sources) == 1
    assert sources[0]["evidence_level"] == "fetched_page"
    assert sources[0]["full_content"] == JAMAICA_PAGE
    assert sources[0]["readable_content"] != JAMAICA_PAGE
    assert "Reader Interactions" not in sources[0]["readable_content"]
    assert sources[0]["article_complete"] is True


def test_discovery_snippet_cleaning_does_not_launder_evidence_level():
    processor = SearchResultProcessor()
    snippet = processor.clean_excerpt(
        "![untrusted image](https://evil.example/f.jpg) "
        "Read [History of Jamaica](https://example.org/a) and <b>facts</b>."
    )
    assert snippet == "Read History of Jamaica and facts."
    assert "https://" not in snippet


def test_html_and_script_attributes_never_become_rendered_markup():
    processor = SearchResultProcessor()
    doc = (
        "<p>Jamaica's political history includes emancipation, resistance, "
        "independence and international migration.</p> "
        "<a href='javascript:alert(1)' onclick='alert(1)'>Learn more</a> "
        "The nation developed a parliamentary system after the end of colonial rule."
    )
    cleaned = processor.clean_excerpt(doc)
    assert "<p>" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "Learn more" in cleaned


def test_cleanup_is_bounded_even_for_oversized_crawl():
    processor = SearchResultProcessor()
    repeated = (
        "Jamaica gained independence in 1962. "
        "Its political and cultural history remains relevant to Caribbean studies. "
    ) * 15000
    result = _result(repeated)
    chunks = processor.process([result], "Jamaica history")
    assert len(chunks) <= 15
    assert len(processor.readable_preview(result, limit=800)) <= 800


def test_retrieval_status_never_claims_verified_model_generation():
    service = object.__new__(InternetCapabilityService)
    summary = service._build_summary(
        query="History of Jamaica", mode="general", execution_time_ms=16000,
        degraded=False, warnings=[],
        sources=[{"url": "https://example.org/jamaica", "evidence_level": "fetched_page"}],
        results=[{"url": "https://example.org/jamaica", "snippet": "A source passage."}],
    )
    assert "not generated an answer" in summary
    assert "16" not in summary
    assert "https://" not in summary
    assert "A source passage" not in summary
