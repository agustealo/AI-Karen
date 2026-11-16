"""KPLUG-CONV-01A: conversational plugin catalog is governed and read-only."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.cortex.routing_intents import (
    parse_plugin_inspection_request,
    resolve_capability_decision,
)
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
from ai_karen_engine.services.plugin_service import PluginService

USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _request(text: str, *, authenticated: bool = True) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": text}],
        context=ChatExecutionContext(
            user_id=USER,
            tenant_id=TENANT,
            session_id="plugin-session",
            request_id="plugin-request",
            correlation_id="plugin-correlation",
            roles=["user"],
            authenticated_user=(
                UserData(user_id=USER, tenant_id=TENANT, roles=["user"])
                if authenticated else None
            ),
        ),
    )


def _plan(*, cap: bool = True, tenant_id: str = TENANT) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="plugin-inspection",
        policy_decision_id="policy-plugin-inspection",
        authorized_user_id=USER,
        authorized_tenant_id=tenant_id,
        authorized_session_id="plugin-session",
        allowed_capabilities=["plugin.inspect"] if cap else [],
        topology=ExecutionTopology.DIRECT,
        budget=ExecutionBudget(
            max_duration_ms=30000, max_tool_calls=3, max_model_calls=0,
        ),
    )


def _meter(plan: AuthorizedExecutionPlan) -> ExecutionBudgetMeter:
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    return meter


def _catalog():
    telegram = SimpleNamespace(
        name="telegram-bot", display_name="Telegram Bot Channel",
        category="communication", tags=["telegram", "messaging", "channel"],
        rbac=SimpleNamespace(allowed_roles=["admin"]),
        capabilities=SimpleNamespace(
            communication_channel=SimpleNamespace(
                inbound={"text"}, outbound={"text"},
            ),
        ),
    )
    generic = SimpleNamespace(
        name="timezone-clock", display_name="Timezone Clock",
        category="utility", tags=["clock"],
        rbac=SimpleNamespace(allowed_roles=["user", "admin"]),
        capabilities=SimpleNamespace(
            communication_channel=None, provides_api=True, provides_ui=True,
        ),
    )
    records = [
        {"manifest": telegram, "status": "disabled", "is_valid": True},
        {"manifest": generic, "status": "enabled", "is_valid": True},
    ]
    service = object.__new__(PluginService)
    service.list_plugins = AsyncMock(return_value=records)
    service._get_kernel = lambda: SimpleNamespace(
        get_channel_activation_manifest=lambda plugin_id: (
            telegram if plugin_id == "telegram-bot" else None
        ),
    )
    service._execution_configuration_readiness = AsyncMock(return_value=None)
    return service


@pytest.mark.parametrize("phrase,operation,target", [
    ("Set up my Telegram", "setup", "Telegram"),
    ("Connect my Telegram", "setup", "Telegram"),
    ("Continue setting up Telegram", "resume", "Telegram"),
    ("Continue setting it up", "resume", None),
    ("Is my Telegram connected?", "status", "Telegram"),
    ("What can my Telegram plugin do?", "features", "Telegram"),
    ("Show my plugins", "list", None),
    ("Which plugins can you use?", "list", None),
    ("Enable my Timezone Clock plugin", "manage", "Timezone Clock"),
    ("Disable my Timezone Clock plugin", "manage", "Timezone Clock"),
    ("Uninstall the Telegram Bot Channel integration", "manage", "Telegram Bot Channel"),
    ("Use my Timezone Clock plugin to tell me the time", "use", "Timezone Clock"),
    ("Run my ArticleButtler plugin to draft an article", "use", "ArticleButtler"),
    ("Which installed plugins can I use to write articles?", "discover", None),
])
def test_plugin_intents_have_typed_read_only_discovery(phrase, operation, target):
    parsed = parse_plugin_inspection_request(phrase)
    assert parsed is not None
    assert parsed.operation == operation
    assert parsed.target == target
    decision = resolve_capability_decision(phrase)
    assert decision.intent == "plugin.inspect"
    assert decision.capability == "plugin.inspect"
    assert decision.requires_live_data
    assert not decision.allow_llm_only


@pytest.mark.parametrize("phrase", [
    "How do I set up Telegram bots in Python?",
    "Explain the Telegram plugin architecture.",
    "Show me your plugin source code.",
    "set up my Telegram and send a message to a stranger",
    "https://example.org",
])
def test_conceptual_requests_and_compound_mutations_are_not_setup_inspections(phrase):
    assert parse_plugin_inspection_request(phrase) is None


@pytest.mark.asyncio
async def test_cortex_routes_setup_to_direct_read_only_capability():
    decision = CortexExecutionDecider(force_graph=False)
    decision._intelligence = SimpleNamespace(analyze=AsyncMock(
        return_value=SimpleNamespace(
            intent="general_assist", intent_confidence=0.91,
            task_complexity="simple", topics=[], memory_relevance=0.0,
            topology_signals={}, risk_signals={"score": 0.0, "categories": []},
            capability_hints={}, reasoning_modes=[],
        ),
    ))
    actual = await decision.decide(_request("Set up my Telegram"))
    assert actual.intent == "plugin.inspect"
    assert actual.topology is ExecutionTopology.DIRECT
    assert actual.graph_required is False
    assert actual.required_capabilities == ["plugin.inspect"]
    assert actual.plugin_candidates == []
    assert actual.tool_requirements == []
    assert actual.policy_constraints["direct_capability"] is True


@pytest.mark.asyncio
async def test_catalog_distinguishes_host_channel_from_generic_execution():
    service = _catalog()
    actual = await service.inspect_for_conversation(tenant_id=TENANT, target="Telegram")
    assert actual["status"] == "found"
    assert actual["catalog_source"] == "plugin_kernel"
    assert actual["mutation_performed"] is False
    assert len(actual["matches"]) == 1
    channel = actual["matches"][0]
    assert channel["installation_id"] == "telegram-bot"
    assert channel["execution_route"] == "channel_host"
    assert channel["channel_host_eligible"] is True
    assert channel["generic_execution_enabled"] is False
    assert channel["connection_status"] == "not_inspected"
    assert channel["credential_status"] == "not_inspected"
    assert channel["provider_send_verified"] is False
    assert channel["provider_delivery_verified"] is False
    assert channel["next_action"] == "channel.inspect_owned_connections"
    assert "channel.inbound.text" in channel["declared_features"]
    assert "channel.outbound.text" in channel["declared_features"]
    service._execution_configuration_readiness.assert_not_awaited()
    assert "vault://" not in json.dumps(actual)


@pytest.mark.asyncio
async def test_catalog_readiness_uses_existing_generic_configuration_owner():
    service = _catalog()
    result = await service.inspect_for_conversation(
        tenant_id=TENANT, target="timezone-clock",
    )
    plugin = result["matches"][0]
    assert plugin["execution_route"] == "plugin_executor"
    assert plugin["readiness"] == "ready"
    assert plugin["generic_execution_enabled"] is True
    service._execution_configuration_readiness.assert_awaited_once_with(
        "timezone-clock", TENANT
    )


@pytest.mark.asyncio
async def test_catalog_fails_closed_on_ambiguous_or_unknown_target():
    service = _catalog()
    no_match = await service.inspect_for_conversation(
        tenant_id=TENANT, target="unregistered-provider",
    )
    assert no_match["status"] == "not_found"
    assert no_match["matches"] == []
    service = _catalog()
    records = await service.list_plugins()
    competing = SimpleNamespace(
        name="another-telegram", display_name="Another Telegram",
        category="communication", tags=["telegram"],
        capabilities=SimpleNamespace(communication_channel=SimpleNamespace(
            inbound={"text"}, outbound={"text"},
        )),
    )
    service.list_plugins.return_value = [
        *records, {"manifest": competing, "status": "disabled", "is_valid": True},
    ]
    result = await service.inspect_for_conversation(
        tenant_id=TENANT, target="telegram",
    )
    assert result["status"] == "ambiguous"
    assert len(result["matches"]) == 2


@pytest.mark.asyncio
async def test_direct_runtime_authorized_inspection_never_executes_plugin():
    service = _catalog()
    service.execute_plugin = AsyncMock()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Set up my Telegram"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.handled and result.success
    assert result.source == "plugin_catalog"
    assert "have not been verified" in result.text
    assert result.payload["plugin_inspection"]["matches"][0]["installation_id"] == "telegram-bot"
    assert result.normalized_metadata()["structured_content"]["plugin_inspection"]["mutation_performed"] is False
    service.execute_plugin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized,authenticated,tenant", [
    (False, True, TENANT),
    (True, False, TENANT),
    (True, True, "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
])
async def test_direct_runtime_denies_untrusted_or_unscoped_inspection(
    authorized, authenticated, tenant,
):
    service = _catalog()
    plan = _plan(cap=authorized, tenant_id=tenant)
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Set up my Telegram", authenticated=authenticated),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.handled and not result.success and result.degraded
    service.list_plugins.assert_not_awaited()


@pytest.mark.asyncio
async def test_unscoped_resume_requires_target_without_guessing_plugin():
    service = _catalog()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Continue setting it up"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert result.payload["status"] == "needs_input"
    assert result.payload["next_action"] == "ask_plugin_target"
    service.list_plugins.assert_not_awaited()


@pytest.mark.parametrize("phrase,action", [
    ("Enable my Timezone Clock plugin", "enable"),
    ("Disable my Timezone Clock plugin", "disable"),
    ("Uninstall the Telegram Bot Channel integration", "uninstall"),
    ("Use my Timezone Clock plugin to tell me the time", "execute"),
    ("Run my ArticleButtler plugin to draft an article", "execute"),
])
def test_generic_interaction_request_preserves_operation_not_authority(phrase, action):
    parsed = parse_plugin_inspection_request(phrase)
    assert parsed is not None
    assert parsed.requested_action == action
    assert parsed.operation in {"manage", "use"}
    routed = resolve_capability_decision(phrase)
    assert routed.capability == "plugin.inspect"
    assert routed.preferred_plugin is None
    assert routed.handler is None
    assert not routed.allow_llm_only


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase,expected_action", [
    ("Use my Timezone Clock plugin to tell me the time", "execute"),
    ("Enable my Timezone Clock plugin", "enable"),
    ("Disable my Timezone Clock plugin", "disable"),
])
async def test_every_plugin_action_first_inspects_without_executing(phrase, expected_action):
    service = _catalog()
    service.execute_plugin = AsyncMock()
    service.enable_plugin = AsyncMock()
    service.disable_plugin = AsyncMock()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request(phrase),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success and result.source == "plugin_catalog"
    assert "has NOT been performed" in result.text
    assert result.payload["requested_action"] == expected_action
    assert result.payload["requested_action_executed"] is False
    assert result.payload["requires_fresh_action_authorization"] is True
    assert result.payload["plugin_inspection"]["mutation_performed"] is False
    assert result.payload["plugin_inspection"]["matches"][0]["installation_id"] == "timezone-clock"
    service.execute_plugin.assert_not_awaited()
    service.enable_plugin.assert_not_awaited()
    service.disable_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_plugin_features_and_role_eligibility_are_manifest_sourced():
    service = _catalog()
    generic = await service.inspect_for_conversation(
        tenant_id=TENANT, target="timezone-clock", caller_roles=["user"],
    )
    record = generic["matches"][0]
    assert record["role_eligible"] is True
    assert record["role_check_source"] == "manifest_rbac"
    assert record["authorized_to_execute"] is False
    assert record["declared_features"] == ["plugin.api", "plugin.ui"]

    channel = await service.inspect_for_conversation(
        tenant_id=TENANT, target="telegram", caller_roles=["user"],
    )
    item = channel["matches"][0]
    assert item["role_eligible"] is False
    assert item["authorized_to_execute"] is False
    assert item["execution_route"] == "channel_host"
    assert "plugin.api" not in item["declared_features"]


@pytest.mark.asyncio
async def test_generic_feature_request_reports_manifest_not_live_execution():
    service = _catalog()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("What can my Timezone Clock plugin do?"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert "plugin.api" in result.text
    assert "plugin.ui" in result.text
    assert "not verified execution" in result.text
    assert result.payload["requested_operation"] == "features"
    assert result.payload["requested_action_executed"] is False


@pytest.mark.asyncio
async def test_generic_plugin_inventory_does_not_claim_ability_to_invoke():
    service = _catalog()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Show my plugins"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert "Telegram Bot Channel" in result.text
    assert "Timezone Clock" in result.text
    assert "Package inventory does not prove permission" in result.text
    assert result.payload["requested_operation"] == "list"
    assert result.payload["requested_action_executed"] is False


@pytest.mark.parametrize("phrase", [
    "Enable my Timezone Clock plugin and delete all messages",
    "Disable my Timezone Clock plugin then restart the server",
    "Use my plugin to",
    "Use my Timezone Clock plugin with password secret",
])
def test_generic_plugin_intent_does_not_approve_compound_or_unbounded_requests(phrase):
    assert parse_plugin_inspection_request(phrase) is None


@pytest.mark.asyncio
async def test_new_generic_plugin_is_discovered_from_manifest_without_code_alias():
    service = _catalog()
    installed = await service.list_plugins()
    article_writer = SimpleNamespace(
        name="articlebuttler", display_name="ArticleButtler",
        category="publishing", tags=["articles", "content-writing"],
        rbac=SimpleNamespace(allowed_roles=["user", "admin"]),
        capabilities=SimpleNamespace(
            communication_channel=None, voice_modality=None,
            provides_api=True, provides_ui=True,
        ),
    )
    service.list_plugins.return_value = [
        *installed,
        {"manifest": article_writer, "status": "enabled", "is_valid": True},
    ]
    result = await service.inspect_for_conversation(
        tenant_id=TENANT, target="ArticleButtler", caller_roles=["user"],
    )
    assert result["status"] == "found"
    plugin = result["matches"][0]
    assert plugin["installation_id"] == "articlebuttler"
    assert plugin["category"] == "publishing"
    assert plugin["execution_route"] == "plugin_executor"
    assert plugin["role_eligible"] is True
    assert plugin["authorized_to_execute"] is False
    assert plugin["declared_features"] == ["plugin.api", "plugin.ui"]
    service._execution_configuration_readiness.assert_awaited_once_with(
        "articlebuttler", TENANT,
    )


@pytest.mark.asyncio
async def test_voice_plugin_is_reported_through_existing_voice_runtime_authority():
    service = _catalog()
    installed = await service.list_plugins()
    voice = SimpleNamespace(
        name="local-speech", display_name="Local Speech",
        category="voice", tags=["tts", "speech"],
        rbac=SimpleNamespace(allowed_roles=["user"]),
        capabilities=SimpleNamespace(
            communication_channel=None,
            voice_modality=SimpleNamespace(modalities=["tts", "stt"]),
            provides_api=True, provides_ui=False,
        ),
    )
    service.list_plugins.return_value = [
        *installed,
        {"manifest": voice, "status": "enabled", "is_valid": True},
    ]
    result = await service.inspect_for_conversation(
        tenant_id=TENANT, target="Local Speech", caller_roles=["user"],
    )
    record = result["matches"][0]
    assert record["installation_id"] == "local-speech"
    assert record["execution_route"] == "voice_runtime"
    assert record["readiness"] == "requires_authorized_voice_catalog"
    assert record["next_action"] == "voice.inspect_engine_catalog"
    assert record["declared_features"] == ["plugin.api", "voice.tts", "voice.stt"]
    assert record["authorized_to_execute"] is False
    service._execution_configuration_readiness.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_use_request_does_not_bypass_channel_operator_roles():
    service = _catalog()
    service.execute_plugin = AsyncMock()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Use my Telegram to send hello"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert "does not match the plugin's declared operator roles" in result.text
    assert result.payload["requested_operation"] == "use"
    assert result.payload["requested_action"] == "execute"
    assert result.payload["requested_action_executed"] is False
    service.execute_plugin.assert_not_awaited()
