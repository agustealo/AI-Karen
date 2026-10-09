from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.direct_capability_executor import (
    DirectCapabilityExecutor,
    DirectCapabilityResult,
)
from ai_karen_engine.services.plugin_service import ExecutionStatus
from ai_karen_engine.services.search.web_search_client import WebSearchClient
from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
    InternetSearchRequest,
)
from ai_karen_engine.services.tooling.tool_service import ToolInput, ToolService
from ai_karen_engine.tools.web_search_tool import WebSearchTool

USER_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONVERSATION_ID = "22222222-2222-2222-2222-222222222222"


def _request(text: str, *, metadata=None) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": text}],
        context=ChatExecutionContext(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            session_id="session-1",
            conversation_id=CONVERSATION_ID,
            request_id="req-1",
            correlation_id="corr-1",
            roles=["user"],
            permissions=["user"],
        ),
        metadata=dict(metadata or {}),
    )


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.92,
        task_complexity="simple",
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={"score": 0.0, "categories": []},
        capability_hints={},
        reasoning_modes=[],
    )


def _plan(*, tools=None, plugins=None, capabilities=None) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id=USER_ID,
        authorized_tenant_id=TENANT_ID,
        authorized_session_id="session-1",
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=list(capabilities or []),
        allowed_tools=list(tools or []),
        allowed_plugins=list(plugins or []),
        budget=ExecutionBudget(
            max_duration_ms=30_000,
            max_model_calls=2,
            max_tool_calls=4,
            max_external_requests=5,
            max_output_tokens=4096,
        ),
    )


@pytest.mark.asyncio
async def test_cortex_weather_is_direct_governed_capability() -> None:
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )

    decision = await decider.decide(
        _request("What's the weather in Detroit?")
    )

    assert decision.intent == "search.weather"
    assert decision.graph_required is False
    assert decision.topology is ExecutionTopology.DIRECT
    assert "web.search" in decision.required_capabilities
    assert "web_search" in decision.tool_requirements
    assert "intelligent-search" in decision.plugin_candidates
    assert "direct_capability_request" in decision.reason_codes


@pytest.mark.asyncio
async def test_cortex_time_uses_time_query_without_inventing_parallel_tool() -> None:
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )

    decision = await decider.decide(
        _request("What time is it in Detroit?")
    )

    assert decision.intent == "time.current"
    assert decision.graph_required is False
    assert decision.topology is ExecutionTopology.DIRECT
    assert "time_query" in decision.required_capabilities
    assert "time-query" in decision.plugin_candidates
    assert "time_tool" not in decision.tool_requirements


@pytest.mark.asyncio
async def test_weather_route_survives_intelligence_analyzer_failure() -> None:
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(side_effect=RuntimeError("model unavailable"))
    )

    decision = await decider.decide(
        _request("What's the weather in Detroit?")
    )

    assert decision.intent == "search.weather"
    assert decision.topology is ExecutionTopology.DIRECT
    assert decision.graph_required is False
    assert decision.required_capabilities == ["web.search"]
    assert decision.tool_requirements == ["web_search"]
    assert decision.plugin_candidates == ["intelligent-search"]


@pytest.mark.asyncio
async def test_direct_time_capability_executes_authorized_plugin() -> None:
    executor = DirectCapabilityExecutor()
    request = _request("What time is it in Detroit?")
    decision = await _time_decision()
    plan = _plan(
        plugins=["time-query"],
        capabilities=["time_query"],
    )
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()

    plugin_service = SimpleNamespace(
        execute_plugin=AsyncMock(
            return_value=SimpleNamespace(
                status=ExecutionStatus.COMPLETED,
                result={
                    "status": "success",
                    "value": "4:30 PM",
                    "label": "Detroit",
                },
                error=None,
            )
        )
    )

    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=plugin_service,
    ):
        result = await executor.execute(
            request=request,
            decision=decision,
            plan=plan,
            meter=meter,
        )

    assert result.handled is True
    assert result.success is True
    assert result.source == "plugin"
    assert result.source_id == "time-query"
    assert "Detroit" in result.text
    assert "4:30 PM" in result.text

    call = plugin_service.execute_plugin.await_args.kwargs
    assert call["authorized_plan"] is plan
    assert call["user_id"] == USER_ID
    assert call["tenant_id"] == TENANT_ID
    assert call["parameters"]["mode"] == "world_time"
    assert call["parameters"]["query"] == "Detroit"


@pytest.mark.asyncio
async def test_weather_prefers_authorized_web_tool_before_plugin() -> None:
    executor = DirectCapabilityExecutor()
    request = _request("What's the weather in Detroit?")
    decision = await _weather_decision()
    plan = _plan(
        tools=["web_search"],
        plugins=["intelligent-search"],
        capabilities=["web.search"],
    )
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()

    plugin_service = SimpleNamespace(
        execute_plugin=AsyncMock(
            return_value=SimpleNamespace(
                status=ExecutionStatus.COMPLETED,
                result={
                    "status": "ok",
                    "results": [{"snippet": "plugin should not run"}],
                },
                error=None,
            )
        )
    )
    tool_service = SimpleNamespace(
        execute_tool=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                result={
                    "status": "ok",
                    "mode": "weather",
                    "results": [
                        {
                            "snippet": (
                                "Detroit is 61°F with light rain and a "
                                "40% chance of precipitation."
                            )
                        }
                    ],
                    "sources": [],
                    "citations": [],
                },
                error=None,
            )
        )
    )

    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=plugin_service,
    ), patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
        return_value=tool_service,
    ):
        result = await executor.execute(
            request=request,
            decision=decision,
            plan=plan,
            meter=meter,
        )

    assert result.handled is True
    assert result.success is True
    assert result.source == "tool"
    assert result.source_id == "web_search"
    assert "61°F" in result.text
    assert len(result.attempts) == 1
    plugin_service.execute_plugin.assert_not_awaited()

    tool_input = tool_service.execute_tool.await_args.args[0]
    assert tool_input.tool_name == "web_search"
    assert tool_input.parameters["mode"] == "weather"
    assert tool_input.user_context["authorized_plan"] is plan
    assert tool_input.user_context["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_missing_live_capability_returns_actionable_continuation() -> None:
    executor = DirectCapabilityExecutor()
    request = _request("What's the weather in Detroit?")
    decision = await _weather_decision()
    plan = _plan(capabilities=["web.search"])
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()

    result = await executor.execute(
        request=request,
        decision=decision,
        plan=plan,
        meter=meter,
    )

    assert result.handled is True
    assert result.success is False
    assert result.degraded is True
    assert result.source == "capability_unavailable"
    assert result.payload["next_action"] == "inspect_authorized_execution_plan"
    assert "not authorized" in result.text.lower()
    assert "check your phone" not in result.text.lower()


@pytest.mark.asyncio
async def test_web_search_tool_forwards_runtime_scope_and_plan() -> None:
    tool = WebSearchTool()
    service = SimpleNamespace(execute=AsyncMock(return_value={"status": "ok"}))
    tool._service = service

    plan = _plan(
        tools=["web_search"],
        capabilities=["web.search"],
    )

    result = await tool._execute(
        {
            "query": "weather Detroit",
            "mode": "weather",
            "max_urls": 3,
        },
        {
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "user_id": USER_ID,
            "tenant_id": TENANT_ID,
            "session_id": "session-1",
            "conversation_id": CONVERSATION_ID,
            "policy_decision_id": "policy-1",
            "allowed_capabilities": ["web.search"],
            "authorized_plan": plan,
        },
    )

    assert result == {"status": "ok"}
    call = service.execute.await_args
    assert call.kwargs["authorized_plan"] is plan
    context = call.kwargs["context"]
    assert context.request_id == "req-1"
    assert context.correlation_id == "corr-1"
    assert context.user_id == USER_ID
    assert context.tenant_id == TENANT_ID
    assert context.session_id == "session-1"
    assert context.conversation_id == CONVERSATION_ID




def test_tool_cache_key_is_scoped_by_tenant_user_and_session() -> None:
    service = ToolService()

    first = ToolInput(
        tool_name="web_search",
        parameters={"query": "weather Detroit", "mode": "weather"},
        user_context={"tenant_id": "tenant-a"},
        user_id="user-a",
        session_id="session-a",
    )
    second = ToolInput(
        tool_name="web_search",
        parameters={"query": "weather Detroit", "mode": "weather"},
        user_context={"tenant_id": "tenant-b"},
        user_id="user-b",
        session_id="session-b",
    )

    assert service._generate_cache_key(first) != service._generate_cache_key(second)


async def _weather_decision():
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )
    return await decider.decide(
        _request("What's the weather in Detroit?")
    )


async def _time_decision():
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )
    return await decider.decide(
        _request("What time is it in Detroit?")
    )


def test_live_capability_patterns_do_not_hijack_unrelated_prompts() -> None:
    time_complexity = resolve_capability_decision(
        "What time complexity does binary search have?"
    )
    incidental_latest = resolve_capability_decision(
        "Explain why our latest refactor changed the cache key."
    )
    temperature_scaling = resolve_capability_decision(
        "Explain temperature scaling for classifier calibration."
    )
    current_directory = resolve_capability_decision(
        "What is the current directory?"
    )
    distributed_time = resolve_capability_decision(
        "Explain time in distributed systems"
    )
    economics_forecast = resolve_capability_decision(
        "How do economists forecast?"
    )
    economic_forecast = resolve_capability_decision(
        "economic forecast"
    )
    quantum_time = resolve_capability_decision("time in quantum mechanics")
    literature_time = resolve_capability_decision("time in literature")
    election_forecast = resolve_capability_decision("election forecast")
    demand_forecast = resolve_capability_decision("demand forecast")
    us_election_forecast = resolve_capability_decision(
        "United States election forecast"
    )

    assert time_complexity.intent == "general.chat"
    assert time_complexity.requires_tool is False
    assert incidental_latest.intent == "general.chat"
    assert incidental_latest.requires_tool is False
    assert temperature_scaling.intent == "general.chat"
    assert temperature_scaling.requires_tool is False
    assert current_directory.intent == "general.chat"
    assert current_directory.requires_tool is False
    assert distributed_time.intent == "general.chat"
    assert distributed_time.requires_tool is False
    assert economics_forecast.intent == "general.chat"
    assert economics_forecast.requires_tool is False
    assert economic_forecast.intent == "general.chat"
    assert economic_forecast.requires_tool is False
    assert quantum_time.intent == "general.chat"
    assert quantum_time.requires_tool is False
    assert literature_time.intent == "general.chat"
    assert literature_time.requires_tool is False
    assert election_forecast.intent == "general.chat"
    assert election_forecast.requires_tool is False
    assert demand_forecast.intent == "general.chat"
    assert demand_forecast.requires_tool is False
    assert us_election_forecast.intent == "general.chat"
    assert us_election_forecast.requires_tool is False


def test_live_capability_patterns_keep_explicit_requests_deterministic() -> None:
    current_time = resolve_capability_decision("What time is it in Detroit?")
    shorthand_time = resolve_capability_decision("time in Detroit")
    current_search = resolve_capability_decision(
        "Search the internet for the latest Python security release."
    )
    detroit_weather = resolve_capability_decision("Detroit weather")
    detroit_forecast = resolve_capability_decision("Detroit forecast")
    long_location_weather = resolve_capability_decision(
        "New York City, New York, United States weather"
    )
    bitcoin_price = resolve_capability_decision("Find current Bitcoin price")
    python_release = resolve_capability_decision("Find the latest Python release")
    latest_python_question = resolve_capability_decision(
        "What is the latest Python release?"
    )
    bitcoin_price_question = resolve_capability_decision(
        "Which is the current Bitcoin price?"
    )
    future_weather = resolve_capability_decision(
        "What will the weather be in Detroit?"
    )
    lower_city_weather = resolve_capability_decision("detroit weather")
    title_city_weather = resolve_capability_decision("New York City weather")
    polite_time = resolve_capability_decision("Please tell me the time in Tokyo")
    wrapped_time = resolve_capability_decision(
        "Could you tell me what time it is in Tokyo?"
    )
    weather_like = resolve_capability_decision(
        "What's the weather like in Detroit?"
    )
    forecast_question = resolve_capability_decision(
        "What is the forecast for Detroit?"
    )
    latest_python_version = resolve_capability_decision("latest Python version")
    latest_ukraine_news = resolve_capability_decision("latest news on Ukraine")
    current_stock_price = resolve_capability_decision(
        "current stock price for AAPL"
    )

    assert current_time.intent == "time.current"
    assert current_time.requires_live_data is True
    assert shorthand_time.intent == "time.current"
    assert shorthand_time.requires_live_data is True
    assert current_search.intent == "search.general"
    assert current_search.requires_live_data is True
    assert detroit_weather.intent == "search.weather"
    assert detroit_weather.requires_live_data is True
    assert detroit_forecast.intent == "general.chat"
    assert detroit_forecast.requires_tool is False
    assert long_location_weather.intent == "search.weather"
    assert long_location_weather.requires_live_data is True
    assert bitcoin_price.intent == "search.general"
    assert bitcoin_price.requires_live_data is True
    assert python_release.intent == "search.general"
    assert python_release.requires_live_data is True
    assert latest_python_question.intent == "search.general"
    assert latest_python_question.requires_live_data is True
    assert bitcoin_price_question.intent == "search.general"
    assert bitcoin_price_question.requires_live_data is True
    assert future_weather.intent == "search.weather"
    assert future_weather.requires_live_data is True
    assert lower_city_weather.intent == "general.chat"
    assert lower_city_weather.requires_tool is False
    assert title_city_weather.intent == "search.weather"
    assert title_city_weather.requires_live_data is True
    assert polite_time.intent == "time.current"
    assert wrapped_time.intent == "time.current"
    assert weather_like.intent == "search.weather"
    assert forecast_question.intent == "search.weather"
    assert latest_python_version.intent == "search.general"
    assert latest_ukraine_news.intent == "search.general"
    assert current_stock_price.intent == "search.general"


@pytest.mark.asyncio
async def test_direct_live_executor_never_preempts_required_workflow() -> None:
    executor = DirectCapabilityExecutor()
    decision = await _weather_decision()
    decision.graph_required = True
    decision.topology = ExecutionTopology.WORKFLOW

    assert decision.policy_constraints["direct_capability"] is True
    assert executor.can_handle(decision) is False


def test_internet_capability_has_canonical_default_search_client() -> None:
    service = InternetCapabilityService()
    client = service._resolve_search_client()

    assert isinstance(client, WebSearchClient)
    assert client.registry.select_provider() is not None


def test_internet_capability_preserves_injected_provider_registry() -> None:
    from ai_karen_engine.services.search.web_search_provider_registry import (
        WebSearchProviderDescriptor,
        WebSearchProviderRegistry,
    )

    registry = WebSearchProviderRegistry(
        settings={"search": {"wikipedia": {"enabled": True}}},
        descriptors={
            "wikipedia": WebSearchProviderDescriptor(
                provider_id="wikipedia",
                capabilities=("web.search",),
                health="healthy",
            )
        },
    )
    service = InternetCapabilityService(provider_registry=registry)

    client = service._resolve_search_client()

    assert client.registry is registry
    assert client.registry.select_provider() == "wikipedia"


def test_default_internet_capability_uses_active_runtime_search_settings() -> None:
    settings = {
        "duckduckgo": {"enabled": False, "priority": 100},
        "searxng": {"enabled": False, "priority": 95},
        "brave_search_free": {"enabled": False, "priority": 91},
        "mojeek": {"enabled": False, "priority": 88},
        "startpage": {"enabled": False, "priority": 87},
        "wikipedia": {"enabled": True, "priority": 200},
    }

    with patch(
        "ai_karen_engine.services.tooling.internet_capability_service.get_config_value",
        return_value=settings,
    ):
        service = InternetCapabilityService()

    assert service.provider_registry.select_provider() == "wikipedia"


def test_web_search_registry_honors_configured_priority() -> None:
    from ai_karen_engine.services.search.web_search_provider_registry import (
        WebSearchProviderRegistry,
    )

    registry = WebSearchProviderRegistry(
        settings={
            "search": {
                "duckduckgo": {"enabled": True, "priority": 10},
                "wikipedia": {"enabled": True, "priority": 500},
            }
        }
    )

    assert registry.select_provider() == "wikipedia"


def test_web_search_registry_invalid_priority_does_not_disable_search() -> None:
    from ai_karen_engine.services.search.web_search_provider_registry import (
        WebSearchProviderRegistry,
    )

    registry = WebSearchProviderRegistry(
        settings={
            "search": {
                "duckduckgo": {"enabled": True, "priority": "high"},
                "searxng": {"enabled": False},
                "brave_search_free": {"enabled": False},
                "mojeek": {"enabled": False},
                "startpage": {"enabled": False},
                "wikipedia": {"enabled": True, "priority": 20},
            }
        }
    )

    assert registry.select_provider() == "wikipedia"
    assert registry.sorted_enabled()[0] == "wikipedia"


def test_runtime_search_config_overrides_manifest_bootstrap_defaults() -> None:
    manifest_settings = {
        "duckduckgo": {"enabled": True, "priority": 100},
        "wikipedia": {"enabled": False, "priority": 85},
    }
    runtime_settings = {
        "duckduckgo": {"enabled": False},
        "wikipedia": {"enabled": True, "priority": 500},
    }

    with patch(
        "ai_karen_engine.services.tooling.internet_capability_service.get_config_value",
        return_value=runtime_settings,
    ):
        service = InternetCapabilityService(search_settings=manifest_settings)

    assert service.provider_registry.is_enabled("duckduckgo") is False
    assert service.provider_registry.is_enabled("wikipedia") is True
    assert service.provider_registry.select_provider() == "wikipedia"


def test_web_search_defaults_are_registered_in_central_config() -> None:
    from ai_karen_engine.config.config_manager import DEFAULT_CONFIG

    search = DEFAULT_CONFIG["search"]

    assert search["duckduckgo"]["enabled"] is True
    assert search["duckduckgo"]["priority"] == 100
    assert "searxng" in search


def test_legacy_plugin_search_config_migrates_to_root_authority() -> None:
    from ai_karen_engine.config.config_manager import validate_config

    cfg = {
        "plugins": {
            "intelligent-search": {
                "search": {
                    "duckduckgo": {"enabled": False, "priority": 1},
                    "wikipedia": {"enabled": True, "priority": 500},
                }
            }
        }
    }

    migrated = validate_config(cfg)

    assert migrated["search"]["duckduckgo"]["enabled"] is False
    assert migrated["search"]["wikipedia"]["enabled"] is True
    assert "search" not in migrated["plugins"]["intelligent-search"]


def test_runtime_config_asset_owns_web_search_provider_settings() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    runtime_config = json.loads(
        (root / "config_assets/config.json").read_text(encoding="utf-8")
    )
    legacy_settings = json.loads(
        (
            root
            / "src/ai_karen_engine/config/settings.json"
        ).read_text(encoding="utf-8")
    )

    assert runtime_config["search"]["duckduckgo"]["priority"] == 100
    assert runtime_config["search"]["wikipedia"]["enabled"] is True
    assert "search" not in legacy_settings
    assert "search" not in legacy_settings.get("plugins", {}).get(
        "intelligent-search", {}
    )


@pytest.mark.asyncio
async def test_search_discovery_reports_actual_provider_provenance() -> None:
    class FakeSearchClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def search(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                provider="wikipedia",
                results=[
                    SimpleNamespace(
                        url="https://en.wikipedia.org/wiki/Detroit"
                    )
                ],
            )

    service = InternetCapabilityService(search_client=FakeSearchClient())
    request = InternetSearchRequest.from_payload("Detroit", {})

    urls, providers = await service._get_relevant_urls(
        ["Detroit"],
        {},
        request,
        3,
    )

    assert urls == ["https://en.wikipedia.org/wiki/Detroit"]
    assert providers == ["wikipedia"]
    assert service._provider_name(providers) == "wikipedia"
    assert service._provider_name(["wikipedia", "duckduckgo"]) == "multi_search"


def test_live_intent_patterns_reject_conceptual_suffixes_and_clock_complexity() -> None:
    prompts = (
        "What's the time complexity of binary search?",
        "What is the time complexity of quicksort?",
        "Explain current time complexity",
        "Explain the current price elasticity model",
        "What is the current version control strategy?",
        "What is the current release process?",
    )

    for prompt in prompts:
        decision = resolve_capability_decision(prompt)
        assert decision.intent == "general.chat", prompt
        assert decision.requires_tool is False, prompt


def test_location_shorthand_supports_unicode_proper_names() -> None:
    sao = resolve_capability_decision("São Paulo weather")
    zurich = resolve_capability_decision("Zürich weather")
    tokyo = resolve_capability_decision("東京 weather")
    dubai = resolve_capability_decision("دبي weather")
    tokyo_time = resolve_capability_decision("time in 東京")

    assert sao.intent == "search.weather"
    assert sao.requires_live_data is True
    assert zurich.intent == "search.weather"
    assert zurich.requires_live_data is True
    assert tokyo.intent == "search.weather"
    assert tokyo.requires_live_data is True
    assert dubai.intent == "search.weather"
    assert dubai.requires_live_data is True
    assert tokyo_time.intent == "time.current"
    assert tokyo_time.requires_live_data is True


@pytest.mark.asyncio
async def test_search_provenance_survives_later_expanded_query_timeout() -> None:
    class FakeSearchClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def search(self, **kwargs):
            del kwargs
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    provider="wikipedia",
                    results=[
                        SimpleNamespace(
                            url="https://en.wikipedia.org/wiki/Detroit"
                        )
                    ],
                )
            await asyncio.sleep(60)
            raise AssertionError("unreachable")

    service = InternetCapabilityService(search_client=FakeSearchClient())
    request = InternetSearchRequest.from_payload("Detroit", {})
    provider_sink: list[str] = []

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            service._get_relevant_urls(
                ["Detroit", "Detroit Michigan"],
                {},
                request,
                3,
                provider_sink=provider_sink,
            ),
            timeout=0.02,
        )

    assert provider_sink == ["wikipedia"]


def test_direct_capability_metadata_reports_search_provider_not_wrapper() -> None:
    result = DirectCapabilityResult(
        handled=True,
        text="live",
        success=True,
        source="tool",
        source_id="web_search",
        payload={
            "metadata": {
                "provider": "multi_search",
                "search_providers": ["wikipedia", "duckduckgo"],
                "crawl_provider": "crawl4ai",
            },
        },
    )

    metadata = result.normalized_metadata()

    assert metadata["actual_provider"] is None
    assert metadata["capability_data_provider"] == "multi_search"
    assert metadata["capability_executor"] == "web_search"
    assert metadata["structured_content"]["provider"] == "multi_search"
    assert metadata["structured_content"]["search_providers"] == [
        "wikipedia",
        "duckduckgo",
    ]
    assert metadata["structured_content"]["crawl_provider"] == "crawl4ai"


def test_legacy_search_config_migration_precedes_environment_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from ai_karen_engine.config import config_manager as config_module

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "intelligent-search": {
                        "search": {
                            "duckduckgo": {"enabled": True, "priority": 100}
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "BACKUP_PATH", config_path.with_suffix(".bak"))
    monkeypatch.setenv(
        "KARI_SEARCH",
        json.dumps(
            {
                "duckduckgo": {"enabled": False, "priority": 1},
                "wikipedia": {"enabled": True, "priority": 500},
            }
        ),
    )

    loaded = config_module.load_config()

    assert loaded["search"]["duckduckgo"]["enabled"] is False
    assert loaded["search"]["wikipedia"]["enabled"] is True
    assert "search" not in loaded["plugins"]["intelligent-search"]


def test_noun_first_freshness_questions_route_live_without_conceptual_hijacks() -> None:
    latest_python = resolve_capability_decision(
        "What is the latest version of Python?"
    )
    bitcoin_price = resolve_capability_decision(
        "What is the current price of Bitcoin?"
    )
    version_control = resolve_capability_decision(
        "What is the current version control strategy?"
    )

    assert latest_python.intent == "search.general"
    assert latest_python.requires_live_data is True
    assert bitcoin_price.intent == "search.general"
    assert bitcoin_price.requires_live_data is True
    assert version_control.intent == "general.chat"
    assert version_control.requires_tool is False


def test_first_run_config_honors_search_environment_override_without_persisting_it(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from ai_karen_engine.config import config_manager as config_module

    config_path = tmp_path / "fresh-config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "BACKUP_PATH", config_path.with_suffix(".bak"))
    monkeypatch.setenv(
        "KARI_SEARCH",
        json.dumps(
            {
                "duckduckgo": {"enabled": False, "priority": 1},
                "wikipedia": {"enabled": True, "priority": 500},
            }
        ),
    )

    loaded = config_module.load_config()
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert loaded["search"]["duckduckgo"]["enabled"] is False
    assert loaded["search"]["wikipedia"]["priority"] == 500
    assert persisted["search"]["duckduckgo"]["enabled"] is True
    assert persisted["search"]["wikipedia"]["priority"] == 85


def test_current_time_question_forms_route_live() -> None:
    plain = resolve_capability_decision("What is the current time?")
    tokyo = resolve_capability_decision("What's the current time in Tokyo?")

    assert plain.intent == "time.current"
    assert plain.requires_live_data is True
    assert tokyo.intent == "time.current"
    assert tokyo.requires_live_data is True


def test_bare_freshness_nouns_accept_bounded_subject_suffixes() -> None:
    ukraine = resolve_capability_decision("Latest news about Ukraine")
    lions = resolve_capability_decision("Latest score for the Lions")
    bitcoin = resolve_capability_decision("Current price of Bitcoin")
    version_control = resolve_capability_decision(
        "Current version control strategy"
    )

    assert ukraine.intent == "search.general"
    assert lions.intent == "search.general"
    assert bitcoin.intent == "search.general"
    assert version_control.intent == "general.chat"


def test_location_shorthand_allows_lowercase_name_connectors() -> None:
    rio = resolve_capability_decision("Rio de Janeiro weather")
    isle = resolve_capability_decision("Isle of Man weather")
    rio_time = resolve_capability_decision("time in Rio de Janeiro")

    assert rio.intent == "search.weather"
    assert rio.requires_live_data is True
    assert isle.intent == "search.weather"
    assert isle.requires_live_data is True
    assert rio_time.intent == "time.current"
    assert rio_time.requires_live_data is True


def test_freshness_contractions_and_right_now_clock_forms_route_live() -> None:
    latest_release = resolve_capability_decision(
        "What's the latest Python release?"
    )
    latest_news = resolve_capability_decision("What's the latest news?")
    latest_news_about = resolve_capability_decision(
        "What's the latest news about Ukraine?"
    )
    right_now = resolve_capability_decision("What time is it right now?")

    assert latest_release.intent == "search.general"
    assert latest_release.requires_live_data is True
    assert latest_news.intent == "search.general"
    assert latest_news.requires_live_data is True
    assert latest_news_about.intent == "search.general"
    assert latest_news_about.requires_live_data is True
    assert right_now.intent == "time.current"
    assert right_now.requires_live_data is True


def test_ambiguous_single_subject_forecasts_do_not_hijack_weather() -> None:
    for prompt in ("Bitcoin forecast", "Ethereum forecast", "Demand forecast"):
        decision = resolve_capability_decision(prompt)
        assert decision.intent == "general.chat", prompt
        assert decision.requires_tool is False, prompt

    assert resolve_capability_decision("Detroit weather").intent == "search.weather"
    assert resolve_capability_decision("New York City forecast").intent == "general.chat"
    assert resolve_capability_decision("forecast in Detroit").intent == "search.weather"
    assert resolve_capability_decision("United States election forecast").intent == "general.chat"


def test_weather_shorthand_punctuation_and_conceptual_guard() -> None:
    for query in ("Detroit weather.", "New York City weather!"):
        assert resolve_capability_decision(query).intent == "search.weather"
    for query in ("Weather vs climate", "Weather stripping installation instructions"):
        assert resolve_capability_decision(query).intent == "general.chat"


def test_clock_for_target_is_detected_by_executor() -> None:
    assert DirectCapabilityExecutor._extract_time_location("What time is it for Tokyo?") == "Tokyo"


def test_explanatory_weather_questions_do_not_preempt_chat() -> None:
    for query in (
        "How is weather data collected?",
        "What's weather modeling?",
        "How's the weather different from climate?",
    ):
        assert resolve_capability_decision(query).intent == "general.chat", query

    for query in (
        "How is the weather?",
        "What's the weather in Detroit?",
        "How's the weather for Tokyo?",
    ):
        assert resolve_capability_decision(query).intent == "search.weather", query


def test_routed_targeted_clock_forms_preserve_plugin_destination() -> None:
    for query in (
        "Timezone in Tokyo",
        "time now in Tokyo",
        "What time is it right now in Tokyo?",
        "What's the current time in Tokyo?",
        "current time for Tokyo",
    ):
        assert resolve_capability_decision(query).intent == "time.current", query
        assert DirectCapabilityExecutor._extract_time_location(query) == "Tokyo", query

    assert DirectCapabilityExecutor._extract_time_location("What time is it right now?") is None


def test_forecast_context_requires_weather_or_positive_place_shape() -> None:
    for query in (
        "What is the revenue forecast for next quarter?",
        "Explain the sales forecast for 2027",
        "Bitcoin forecast",
    ):
        assert resolve_capability_decision(query).intent == "general.chat", query
    assert resolve_capability_decision("forecast for Detroit").intent == "search.weather"
    assert resolve_capability_decision("forecast in Tokyo").intent == "search.weather"


def test_trailing_right_now_is_not_part_of_clock_location() -> None:
    query = "What time is it in Tokyo right now?"
    assert resolve_capability_decision(query).intent == "time.current"
    assert DirectCapabilityExecutor._extract_time_location(query) == "Tokyo"


def test_forecast_period_labels_do_not_route_to_weather() -> None:
    q4 = resolve_capability_decision("Forecast for Q4")
    fiscal = resolve_capability_decision("forecast for FY2027")

    assert q4.intent == "general.chat"
    assert q4.requires_tool is False
    assert fiscal.intent == "general.chat"
    assert fiscal.requires_tool is False


def test_time_location_extraction_strips_punctuated_right_now() -> None:
    location = DirectCapabilityExecutor._extract_time_location(
        "What time is it in Tokyo, right now?"
    )

    assert location == "Tokyo"


def test_polite_clock_location_is_forwarded_to_world_time() -> None:
    for prompt in (
        "Please tell me the time in Tokyo",
        "Can you tell me what time it is in Tokyo?",
        "Tell me the current time in New York",
    ):
        assert resolve_capability_decision(prompt).intent == "time.current"
        location = DirectCapabilityExecutor._extract_time_location(prompt)
        assert location in {"Tokyo", "New York"}, (prompt, location)


def test_private_status_queries_do_not_trigger_external_search() -> None:
    for prompt in (
        "What is the current status of my order?",
        "What is the current status of deployment 123?",
        "Find current status of my account",
        "Latest update on my private project",
    ):
        assert resolve_capability_decision(prompt).intent != "search.general", prompt


def test_polite_clock_extracts_every_supported_modal_location() -> None:
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    for query in (
        "Can you tell me the time in Tokyo?",
        "Could you tell me what time it is in Tokyo?",
        "Would you please tell me the time in Tokyo?",
        "Please tell me what time it is in Tokyo?",
    ):
        assert resolve_capability_decision(query).intent == "time.current"
        assert DirectCapabilityExecutor._extract_time_location(query) == "Tokyo"


def test_live_public_updates_without_private_status_hijack() -> None:
    assert resolve_capability_decision("Latest Windows update").intent == "search.general"
    assert resolve_capability_decision("Latest update on Hurricane Milton").intent == "search.general"
    assert resolve_capability_decision("What is the current status of my order?").intent == "general.chat"
    assert resolve_capability_decision("What is the current status of deployment 123?").intent == "general.chat"


def test_private_updates_are_not_external_search_targets() -> None:
    for query in (
        "Latest update on my private project",
        "Current status of our deployment",
        "Latest updates for your internal account",
    ):
        assert resolve_capability_decision(query).intent == "general.chat"


def test_polite_find_current_queries_route_to_live_search() -> None:
    for query in (
        "Please find current Bitcoin price",
        "Can you find the latest Python version?",
        "Could you please find the latest Python version?",
    ):
        assert resolve_capability_decision(query).intent == "search.general"


def test_bare_tell_me_clock_and_possessive_private_updates() -> None:
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    query = "Tell me the current time in New York"
    assert resolve_capability_decision(query).intent == "time.current"
    assert DirectCapabilityExecutor._extract_time_location(query) == "New York"

    for query in (
        "Latest update on his private project",
        "Latest update on her order",
        "Latest update on their account",
        "Latest update on its deployment",
    ):
        assert resolve_capability_decision(query).intent == "general.chat"


def test_inverted_tell_me_clock_and_standalone_private_updates() -> None:
    from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor

    query = "Tell me what time is it in Tokyo"
    assert resolve_capability_decision(query).intent == "time.current"
    assert DirectCapabilityExecutor._extract_time_location(query) == "Tokyo"

    for query in ("Latest update on mine", "Latest update on ours",
                  "Latest update on yours", "Latest update on hers",
                  "Latest update on theirs"):
        assert resolve_capability_decision(query).intent == "general.chat"


@pytest.mark.asyncio
async def test_weather_uses_governed_profile_location_without_a_parallel_memory_read() -> None:
    executor = DirectCapabilityExecutor()
    request = _request("What's the weather?")
    decision = await _weather_decision()
    plan = _plan(tools=["web_search"], capabilities=["web.search"])
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    tool_service = SimpleNamespace(
        execute_tool=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                result={
                    "status": "ok",
                    "results": [{"snippet": "Sourced forecast for DC."}],
                },
                error=None,
            )
        )
    )
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
        return_value=tool_service,
    ):
        result = await executor.execute(
            request=request, decision=decision, plan=plan, meter=meter,
            resolved_context={
                "weather_location": "Washington, DC",
                "location_source": "user_profile",
            },
        )
    assert result.success
    tool_input = tool_service.execute_tool.await_args.args[0]
    assert "Washington, DC" in tool_input.parameters["query"]
    assert tool_input.user_context["authorized_plan"] is plan


@pytest.mark.asyncio
async def test_weather_without_authorized_location_asks_instead_of_searching() -> None:
    executor = DirectCapabilityExecutor()
    request = _request("What's the weather?")
    decision = await _weather_decision()
    plan = _plan(tools=["web_search"], capabilities=["web.search"])
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    tool_service = SimpleNamespace(execute_tool=AsyncMock())
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_tool_service",
        return_value=tool_service,
    ):
        result = await executor.execute(
            request=request, decision=decision, plan=plan, meter=meter,
        )
    assert result.success
    assert "location" in result.text.lower() or "city" in result.text.lower()
    tool_service.execute_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_weather_location_does_not_trigger_private_profile_recall() -> None:
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )
    decision = await decider.decide(_request("What's the weather in Detroit?"))
    assert decision.intent == "search.weather"
    assert decision.memory_recall_required is False


@pytest.mark.asyncio
async def test_missing_weather_location_requests_governed_memory_lookup() -> None:
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(
        analyze=AsyncMock(return_value=_analysis())
    )
    decision = await decider.decide(_request("What's the weather?"))
    assert decision.intent == "search.weather"
    assert decision.memory_recall_required is True
    assert decision.memory_scope == "user"
