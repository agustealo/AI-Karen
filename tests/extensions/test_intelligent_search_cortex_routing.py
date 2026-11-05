"""CORTEX's real capability resolver must preserve consumer search intent."""

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision


def test_current_weather_question_uses_structured_capability():
    decision = resolve_capability_decision("What's the weather in Detroit?")
    assert decision.intent == "search.weather"
    assert decision.requires_live_data is True


def test_weather_without_location_requires_location_context():
    decision = resolve_capability_decision("What's the weather?")
    assert decision.intent == "search.weather"
    assert "location.current" in decision.missing_requirements


def test_weather_band_is_not_forecast_intent():
    decision = resolve_capability_decision("Weather Report jazz albums")
    assert decision.intent != "search.weather"


def test_new_movie_release_queries_are_live_search_not_model_recall():
    for query in (
        "latest movies",
        "what are the latest movies?",
        "new movies this week",
        "movies in theaters now",
        "what movies are in theaters now?",
        "upcoming films",
    ):
        decision = resolve_capability_decision(query)
        assert decision.intent == "search.general", query
        assert decision.requires_live_data is True
        assert decision.capability == "web.search"
        assert decision.allow_llm_only is False


def test_creative_recipe_and_film_discussion_stay_generative_without_forced_search():
    for query in (
        "Write a vegan pasta recipe",
        "Make up a Jamaican curry recipe",
        "Explain the plot of The Matrix",
        "What makes an engaging movie?",
        "What is the time complexity of merge sort?",
        "What is new about my app?",
    ):
        decision = resolve_capability_decision(query)
        assert decision.intent == "general.chat", query
        assert decision.requires_tool is False
