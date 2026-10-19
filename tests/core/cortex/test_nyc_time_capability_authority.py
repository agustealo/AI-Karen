"""Current-time questions must use governed live capability routing.

Tests intent and location extraction, not the availability or correctness
of an external clock service. Live provider/clock proof remains a separate gate.
"""

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest


@pytest.mark.parametrize("question", [
    "Whats the time in NYC",
    "What's the time in NYC?",
    "What is the current time in New York?",
])
def test_nyc_clock_requests_route_to_authorized_live_time(question):
    decision = resolve_capability_decision(question)
    assert decision.intent == "time.current"
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False
    assert decision.capability == "time_query"
    assert DirectCapabilityExecutor._extract_time_location(question) in {"NYC", "New York"}

    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": question}],
        context=ChatExecutionContext(tenant_id="tenant", user_id="user", session_id="session"),
        metadata={"user_timezone": "America/Detroit"},
    )
    params = DirectCapabilityExecutor()._plugin_parameters(
        "time.current", question, request, None,
    )
    assert params["mode"] == "world_time"
    assert params["query"] == DirectCapabilityExecutor._extract_time_location(question)
    # The named city must override the user's own local timezone target.
    assert "timezone" not in params


@pytest.mark.parametrize("question", [
    "What is the time complexity of mergesort?",
    "Tell me about time in literature",
])
def test_conceptual_time_questions_not_hijacked_as_clock(question):
    assert resolve_capability_decision(question).intent != "time.current"
