"""Current movie releases need live evidence, not model recollection."""

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision


@pytest.mark.parametrize("prompt", [
    "latest movies",
    "new films",
    "show me the latest movies",
    "find new movies in theaters",
    "what's the latest movie releases?",
    "list recent film premieres",
])
def test_current_movie_discovery_requires_live_authorized_search(prompt):
    decision = resolve_capability_decision(prompt)
    assert decision.intent == "search.general"
    assert decision.requires_tool is True
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False


@pytest.mark.parametrize("prompt", [
    "Latest news about NASA",
    "What's the latest news about NASA?",
    "What's the latest in technology news?",
])
def test_natural_current_news_requests_require_live_authorized_search(prompt):
    decision = resolve_capability_decision(prompt)
    assert decision.intent == "search.general"
    assert decision.requires_tool is True
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False


@pytest.mark.parametrize("prompt", [
    "Explain film noir",
    "Recommend classic movies",
    "Write a science fiction screenplay",
    "What makes a film memorable?",
])
def test_static_movie_discussion_does_not_require_live_search(prompt):
    decision = resolve_capability_decision(prompt)
    assert decision.intent != "search.general"


@pytest.mark.parametrize("prompt", [
    "Show latest releases in a table",
    "Tabulate the latest movie sources",
    "Give me a tabular list of recent web sources",
    "List the latest news in a table",
    "Show me the new movies as a table",
])
def test_explicit_current_source_table_routes_to_live_search(prompt):
    decision = resolve_capability_decision(prompt)
    assert decision.intent == "search.general"
    assert decision.requires_tool
    assert decision.requires_live_data
    assert decision.allow_llm_only is False


@pytest.mark.parametrize("prompt", [
    "Give me a table of my private status updates",
    "Explain tabular data",
    "Show me a table about movie storytelling",
    "Compare two characters in a film",
])
def test_table_word_does_not_bypass_private_or_model_only_routing(prompt):
    assert resolve_capability_decision(prompt).intent != "search.general"
