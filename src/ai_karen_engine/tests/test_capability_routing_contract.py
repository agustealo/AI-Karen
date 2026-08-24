from ai_karen_engine.core.cortex.routing_intents import CAPABILITY_ROUTES, resolve_capability_decision


def test_capability_registry_contains_live_fact_routes():
    assert "time.current" in CAPABILITY_ROUTES
    assert "search.general" in CAPABILITY_ROUTES
    assert "search.weather" in CAPABILITY_ROUTES


def test_time_query_requires_tool():
    decision = resolve_capability_decision("What time is it in Detroit?")
    assert decision.intent == "time.current"
    assert decision.requires_tool is True
    assert decision.allow_llm_only is False
    assert decision.preferred_plugin == "time-query"


def test_web_search_requires_tool_and_live_data():
    decision = resolve_capability_decision("Search the internet for latest vLLM CUDA issue")
    assert decision.intent == "search.general"
    assert decision.requires_tool is True
    assert decision.requires_live_data is True
    assert decision.capability == "internet_search"


def test_general_chat_allows_llm_only():
    decision = resolve_capability_decision("Tell me a joke")
    assert decision.intent == "general.chat"
    assert decision.requires_tool is False
    assert decision.allow_llm_only is True
