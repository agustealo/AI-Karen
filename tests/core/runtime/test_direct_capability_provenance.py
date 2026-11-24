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


def test_typed_search_options_preserve_restrictions_and_false_preference():
    from ai_karen_engine.core.runtime.chat_runtime_contract import SearchRetrievalOptions
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    options = SearchRetrievalOptions(
        allowed_domains=("example.org",),
        blocked_domains=("private.example.org",),
        time_range="w",
        prefer_recent=False,
        max_urls=3,
    )
    assert DirectCapabilityExecutor._tool_parameters("release notes", "general", options) == {
        "query": "release notes", "mode": "general",
        "allowed_domains": ["example.org"],
        "blocked_domains": ["private.example.org"],
        "time_range": "w", "prefer_recent": False, "max_urls": 3,
    }
    assert DirectCapabilityExecutor._tool_parameters("release notes", "general") == {
        "query": "release notes", "mode": "general",
    }


def test_typed_search_options_reject_invalid_restrictions():
    import pytest

    from ai_karen_engine.core.runtime.chat_runtime_contract import SearchRetrievalOptions

    for invalid in (
        {"allowed_domains": ["example.org"]},
        {"blocked_domains": (" ",)},
        {"max_urls": True},
        {"max_urls": 26},
        {"prefer_recent": "false"},
        {"time_range": " "},
    ):
        with pytest.raises(ValueError):
            SearchRetrievalOptions(**invalid)


def test_general_search_fallback_denied_even_without_retrieval_restrictions():
    from ai_karen_engine.core.runtime.chat_runtime_contract import SearchRetrievalOptions
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    deny = DirectCapabilityExecutor._search_plugin_fallback_denial
    assert deny("search.general", None) == "search_fallback_execution_meter_unverified"
    assert deny("search.general", SearchRetrievalOptions()) == "search_fallback_execution_meter_unverified"
    assert deny("search.general", SearchRetrievalOptions(max_urls=3)) == "search_fallback_execution_meter_unverified"
    assert deny("search.weather", None) is None


def test_governed_fallback_requires_remaining_original_quota():
    import asyncio
    from types import SimpleNamespace
    from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    meter = ExecutionBudgetMeter(ExecutionBudget(max_external_requests=1))
    plan = object()
    context = SimpleNamespace(is_runtime_model_plan_authorized=lambda p, m: p is plan and m is meter)
    deny = DirectCapabilityExecutor._search_plugin_fallback_denial
    assert deny("search.general", None, "intelligent-search", context, plan, meter, "general") is None
    assert deny("search.general", None, "other", context, plan, meter, "general")
    assert deny("search.general", None, "intelligent-search", context, plan, meter, "weather")
    asyncio.run(meter.reserve_external_request())
    assert deny("search.general", None, "intelligent-search", context, plan, meter, "general") == "search_fallback_external_budget_exhausted"
