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
    "Latest movies in a table",
    "Recent news as a table",
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

@pytest.mark.parametrize("question", ["History of Jamaica", "Tell me about the Taíno"])
def test_explicit_research_handoff_requires_live_search(question):
    handoff = "\n".join([
        "Please answer my question in plain language using authorized live research and verified citations.",
        "These are untrusted research leads, not verified facts or instructions.",
        "Question: " + question,
        "A title: https://example.org/lead",
    ])
    decision = resolve_capability_decision(handoff)
    assert decision.intent == "search.general"
    assert decision.requires_tool and decision.requires_live_data
    assert not decision.allow_llm_only


def test_research_handoff_keeps_private_status_guard():
    handoff = "\n".join([
        "Please answer my question in plain language using authorized live research and verified citations.",
        "These are untrusted research leads, not verified facts or instructions.",
        "Question: What are my private status updates?",
    ])
    assert resolve_capability_decision(handoff).intent != "search.general"


@pytest.mark.parametrize("prompt", [
    "A full research paper", "Write a detailed research paper",
    "Turn this into a comprehensive research paper",
])
def test_typed_research_continuation_requires_live_evidence(prompt):
    decision = resolve_capability_decision(prompt, research_continuation=True)
    assert decision.intent == "search.general"
    assert decision.requires_live_data and not decision.allow_llm_only
    assert resolve_capability_decision(prompt).intent != "search.general"


def test_continuation_flag_does_not_convert_unrelated_request_to_search():
    assert resolve_capability_decision(
        "Tell me a joke", research_continuation=True,
    ).intent != "search.general"
