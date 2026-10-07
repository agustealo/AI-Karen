from __future__ import annotations

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
)
from ai_karen_engine.services.plugin_service import ExecutionStatus
from ai_karen_engine.services.search.web_search_client import WebSearchClient
from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
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
    assert result.payload["next_action"] == "enable_or_authorize_capability"
    assert "enable it" in result.text.lower()
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

    assert time_complexity.intent == "general.chat"
    assert time_complexity.requires_tool is False
    assert incidental_latest.intent == "general.chat"
    assert incidental_latest.requires_tool is False
    assert temperature_scaling.intent == "general.chat"
    assert temperature_scaling.requires_tool is False
    assert current_directory.intent == "general.chat"
    assert current_directory.requires_tool is False


def test_live_capability_patterns_keep_explicit_requests_deterministic() -> None:
    current_time = resolve_capability_decision("What time is it in Detroit?")
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

    assert current_time.intent == "time.current"
    assert current_time.requires_live_data is True
    assert current_search.intent == "search.general"
    assert current_search.requires_live_data is True
    assert detroit_weather.intent == "search.weather"
    assert detroit_weather.requires_live_data is True
    assert detroit_forecast.intent == "search.weather"
    assert detroit_forecast.requires_live_data is True
    assert long_location_weather.intent == "search.weather"
    assert long_location_weather.requires_live_data is True
    assert bitcoin_price.intent == "search.general"
    assert bitcoin_price.requires_live_data is True
    assert python_release.intent == "search.general"
    assert python_release.requires_live_data is True


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
