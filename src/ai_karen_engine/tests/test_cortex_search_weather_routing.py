from ai_karen_engine.core.cortex.routing_intents import (
    CAPABILITY_ROUTES,
    resolve_capability_decision,
)


def test_weather_routes_to_internet_search():
    decision = resolve_capability_decision("What's the weather in Westland, MI?")
    assert decision.intent == "search.weather"
    assert decision.capability == "internet_search"
    assert decision.preferred_plugin == "intelligent-search"
    assert decision.handler == "web_search"


def test_weather_capability_contract_is_search_mode():
    route = CAPABILITY_ROUTES["search.weather"]
    assert route["required_capability"] == "internet_search"
    assert route["handler"] == "web_search"
