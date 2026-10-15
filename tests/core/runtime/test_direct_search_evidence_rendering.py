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
