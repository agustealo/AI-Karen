"""Direct live capability failures must be truthful and diagnosable."""

from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def test_weather_plan_denial_does_not_claim_provider_outage():
    result = DirectCapabilityExecutor()._unavailable(
        0.0,
        "web.search",
        "web_search",
        "not_in_authorized_plan",
        [{"type": "tool", "id": "web_search", "status": "skipped", "error": "not_in_authorized_plan"}],
    )
    assert not result.success
    assert result.degraded
    assert "not authorized" in result.text
    assert result.payload["next_action"] == "inspect_authorized_execution_plan"
    assert result.attempts[0]["error"] == "not_in_authorized_plan"


def test_weather_provider_failure_does_not_blame_permissions():
    result = DirectCapabilityExecutor()._unavailable(
        0.0,
        "web.search",
        "web_search",
        "capability_returned_no_live_data",
        [{"type": "tool", "id": "web_search", "status": "failed", "error": "capability_returned_no_live_data"}],
    )
    assert "provider failed or returned no usable result" in result.text
    assert result.payload["next_action"] == "inspect_provider_attempts"
    assert not result.success


def test_weather_unconfigured_path_is_distinct_from_denial():
    result = DirectCapabilityExecutor()._unavailable(
        0.0, "web.search", "web_search", "not available", [],
    )
    assert "No executable live capability" in result.text
    assert result.payload["next_action"] == "inspect_capability_registration"
