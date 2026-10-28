"""Exercise the real direct-capability adapters with governed location context."""
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.core.runtime.location_context import resolve_location


def request(metadata=None):
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "What's the time?"}],
        context=ChatExecutionContext(tenant_id="tenant", user_id="user", session_id="session"),
        metadata=metadata or {},
    )


def test_authorized_runtime_timezone_reaches_time_plugin():
    parameters = DirectCapabilityExecutor()._plugin_parameters(
        "time.current", "What's the time?", request(), None,
        {"timezone": "America/Detroit"},
    )
    assert parameters["mode"] == "time"
    assert parameters["timezone"] == "America/Detroit"


def test_world_clock_city_overrides_runtime_timezone():
    parameters = DirectCapabilityExecutor()._plugin_parameters(
        "time.current", "What's the time in Tokyo?", request(), None,
        {"timezone": "America/Detroit"},
    )
    assert parameters["mode"] == "world_time"
    assert parameters["query"] == "Tokyo"
    assert "timezone" not in parameters


def test_missing_weather_location_yields_no_invented_city():
    assert resolve_location({}, {}, kind="weather") is None
    assert DirectCapabilityExecutor._weather_query_with_location("What's the weather?", {}) is None


def test_weather_followup_city_is_not_lost():
    context = {"pending_clarification": {"missing_requirement": "weather_location"}}
    assert DirectCapabilityExecutor._weather_query_with_location("Detroit", context) == "What's the weather in Detroit?"


def test_streaming_direct_capability_uses_authorized_timezone_evidence():
    from pathlib import Path
    runtime_source = (
        Path(__file__).resolve().parents[3]
        / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    ).read_text()
    start = runtime_source.index("    async def _run_direct_capability_stream(")
    end = runtime_source.index("        normalized = result.normalized_metadata()", start)
    streaming = runtime_source[start:end]
    assert 'attribute="timezone"' in streaming
    assert 'tenant_id=request.context.tenant_id' in streaming
    assert 'user_id=request.context.user_id' in streaming
    assert '{"timezone": resolved_timezone} if resolved_timezone else None' in streaming
