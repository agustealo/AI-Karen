"""Direct capability search responses show source attribution instead of anonymous excerpts."""

from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def test_live_search_passages_have_source_urls():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.general", "Jamaica history", {
        "results": [{"snippet": "Jamaica became independent in 1962.", "url": "https://example.org/history"}]
    })
    assert "Jamaica became independent in 1962." in text
    assert "Source: https://example.org/history" in text
    assert "not a synthesized answer" in text


def test_anonymous_snippet_does_not_look_cited():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.general", "history", {
        "results": [{"snippet": "Unsupported anonymous claim"}],
        "summary": "No fetched evidence available",
    })
    assert "Unsupported anonymous claim" not in text
    assert "No fetched evidence available" in text


def test_weather_without_page_link_still_reports_live_measurement():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.weather", "weather Detroit", {
        "results": [{"snippet": "Detroit is 61°F with light rain."}]
    })
    assert "61°F" in text
    assert "source URL unavailable" in text


def test_evidence_rendering_uses_actual_line_breaks():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.general", "history", {
        "results": [
            {"snippet": "First claim", "url": "https://example.org/first"},
            {"snippet": "Second claim", "url": "https://example.org/second"},
        ]
    })
    assert "First claim\nSource: https://example.org/first" in text
    assert "\n\nSecond claim\nSource: https://example.org/second" in text
    assert r"\nSource:" not in text


def test_weather_measurement_has_real_paragraph_breaks():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.weather", "Detroit weather", {
        "results": [{"snippet": "61 F and rain"}]
    })
    assert "unavailable):\n\n61 F" in text
    assert r"\n\n" not in text


def test_news_excerpts_preserve_headline_and_provider_publication_time():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.general", "What's the latest in Jamaica news?", {
        "results": [{
            "title": "Kingston transport announcement",
            "published_at": "2026-10-14T12:30:00-05:00",
            "snippet": "The transport agency published an update.",
            "url": "https://example.org/jamaica/transport",
        }]
    })
    assert "Headline: Kingston transport announcement" in text
    assert "Published (provider-reported): 2026-10-14T12:30:00-05:00" in text
    assert "Source: https://example.org/jamaica/transport" in text


def test_missing_publication_date_is_not_invented():
    executor = object.__new__(DirectCapabilityExecutor)
    text = executor._render("search.general", "Jamaica news", {
        "results": [{
            "title": "Undated article",
            "snippet": "A source excerpt",
            "url": "https://example.org/undated",
        }]
    })
    assert "Headline: Undated article" in text
    assert "Published" not in text


def test_search_result_articles_are_carried_to_response_sources():
    executor = object.__new__(DirectCapabilityExecutor)
    payload = {
        "results": [{
            "title": "Jamaica news update",
            "published_at": "2026-10-15T10:00:00Z",
            "snippet": "An article with provider evidence.",
            "url": "https://example.org/jamaica",
        }]
    }
    result = executor._success(
        0.0, "search.general", "latest Jamaica news", payload,
        source="tool", source_id="web_search", attempts=[],
    )
    assert result.success is True
    assert result.sources == payload["results"]
    assert result.sources[0]["published_at"] == "2026-10-15T10:00:00Z"


def test_search_response_sources_deduplicate_provider_entries():
    executor = object.__new__(DirectCapabilityExecutor)
    original = {"url": "https://example.org/news", "snippet": "Sourced article"}
    payload = {"sources": [original], "results": [dict(original)]}
    result = executor._success(
        0.0, "search.general", "Jamaica news", payload,
        source="tool", source_id="web_search", attempts=[],
    )
    assert result.sources == [original]


def test_search_response_does_not_promote_unsourced_result_to_source():
    executor = object.__new__(DirectCapabilityExecutor)
    result = executor._success(
        0.0, "search.general", "Jamaica news",
        {"results": [{"snippet": "No verifiable link"}]},
        source="tool", source_id="web_search", attempts=[],
    )
    assert result.sources == []
