"""Direct live tool failures must not masquerade as model-provider switches."""
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityResult


def test_failed_web_search_preserves_capability_failure_not_model_fallback():
    result = DirectCapabilityResult(
        handled=True,
        text="I couldn't retrieve live information.",
        success=False,
        degraded=True,
        source="capability_unavailable",
        source_id="web_search",
        error="no_live_results",
        payload={"required_capability": "web.search", "target": "web_search"},
        attempts=[{"type": "tool", "id": "web_search", "status": "failed", "error": "no_live_results"}],
    )
    metadata = result.normalized_metadata()
    assert metadata["actual_provider"] is None
    assert metadata["actual_model"] is None
    assert metadata["capability_executor"] == "web_search"
    assert metadata["fallback_level"] == 0
    assert metadata["degraded_mode"] is True
    assert metadata["provider_attempts"][0]["error"] == "no_live_results"


def test_successful_search_data_source_is_not_chat_model_provider():
    result = DirectCapabilityResult(
        handled=True,
        text="A sourced result",
        success=True,
        source="tool",
        source_id="web_search",
        payload={"provider": "duckduckgo", "results": [{"snippet": "Live response"}]},
    )
    metadata = result.normalized_metadata()
    assert metadata["actual_provider"] is None
    assert metadata["capability_data_provider"] == "duckduckgo"
    assert metadata["capability_executor"] == "web_search"
    assert metadata["fallback_level"] == 0
