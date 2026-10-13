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
