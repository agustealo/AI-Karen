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
    "Explain film noir",
    "Recommend classic movies",
    "Write a science fiction screenplay",
    "What makes a film memorable?",
])
def test_static_movie_discussion_does_not_require_live_search(prompt):
    decision = resolve_capability_decision(prompt)
    assert decision.intent != "search.general"
