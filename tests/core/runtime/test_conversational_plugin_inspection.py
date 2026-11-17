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


def _request(
    text: str, *, authenticated: bool = True, roles: list[str] | None = None,
) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": text}],
        context=ChatExecutionContext(
            user_id=USER,
            tenant_id=TENANT,
            session_id="plugin-session",
            request_id="plugin-request",
            correlation_id="plugin-correlation",
            roles=roles or ["user"],
            authenticated_user=(
                UserData(user_id=USER, tenant_id=TENANT, roles=roles or ["user"])
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
        get_record=lambda plugin_id: next(
            (record for record in service.list_plugins.return_value
             if record["manifest"].name == plugin_id), None,
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
    assert "not verified" in result.text
    assert "No setup action was performed" in result.text
    assert result.payload["plugin_inspection"]["matches"][0]["installation_id"] == "telegram-bot"
    assert result.payload["plugin_inspection"]["matches"][0]["connection_status"] == "not_inspected"
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
    assert (
        "has NOT been performed" in result.text
        or "No action was performed" in result.text
    )
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


@pytest.mark.asyncio
async def test_cortex_plugin_inspection_cannot_inherit_incidental_ml_tool_hints():
    """No caller's request for a plugin can mint filesystem or web actions."""
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(
        return_value=SimpleNamespace(
            intent="general_assist",
            intent_confidence=0.98,
            task_complexity="complex",
            topics=["development"],
            memory_relevance=0.8,
            topology_signals={
                "code_execution": True, "external_lookup": True,
                "multiple_actions": True,
            },
            risk_signals={"score": 0.0, "categories": []},
            capability_hints={
                "code_execution": True, "web_search": True,
                "filesystem_write": True,
            },
            reasoning_modes=[],
        ),
    ))
    decision = await decider.decide(
        _request("Use my ArticleButtler plugin to debug code")
    )
    assert decision.intent == "plugin.inspect"
    assert decision.topology is ExecutionTopology.DIRECT
    assert decision.graph_required is False
    assert decision.tool_requirements == []
    assert decision.plugin_candidates == []
    assert decision.required_capabilities == ["plugin.inspect"]
    assert decision.workflow_id is None
    assert decision.memory_recall_required is False
    assert decision.memory_write_allowed is False


@pytest.mark.asyncio
async def test_owner_scoped_channel_summary_authorizes_once_using_real_chat_session():
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.host import ChannelHostServices

    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    host._installed = {"telegram-bot": object()}
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda name: (
            object() if name == "telegram-bot" else None
        ),
    )
    host.activation = SimpleNamespace(issue_action_plan=AsyncMock())
    one = ChannelConnection(
        connection_id="owned-one", tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="bot-secret-id",
        credential_handle="vault://never-surface", revision=4, enabled=True,
    )
    two = ChannelConnection(
        connection_id="owned-two", tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="second-secret-id",
        credential_handle="vault://never-surface-two", revision=8, enabled=False,
    )
    host.repository = SimpleNamespace(
        list_personal_owned_connections=AsyncMock(return_value=[one, two]),
    )
    result = await host.inspect_owned_channel_connections(
        tenant_id=TENANT, user_id=USER, session_id="plugin-session",
        request_id="plugin-request", correlation_id="plugin-correlation",
        installation_id="telegram-bot",
    )
    assert result["owned_connection_count"] == 2
    assert result["persisted_enabled_count"] == 1
    assert result["latest_connection_revision"] == 8
    assert result["connection_status"] == "owned_enabled_recorded"
    assert result["provider_registration_verified"] is False
    assert result["provider_delivery_verified"] is False
    assert "vault://" not in json.dumps(result)
    assert "bot-secret-id" not in json.dumps(result)
    host.activation.issue_action_plan.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, session_id="plugin-session",
        installation_id="telegram-bot", action="channel.consent",
    )
    host.repository.list_personal_owned_connections.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )


@pytest.mark.asyncio
async def test_no_owned_channel_still_requires_fresh_consent_before_reporting_none():
    from ai_karen_engine.services.channels.host import ChannelHostServices

    host = object.__new__(ChannelHostServices)
    host._initialized, host._closed = True, False
    host._installed = {"telegram-bot": object()}
    host.kernel = SimpleNamespace(get_channel_activation_manifest=lambda name: object())
    host.activation = SimpleNamespace(
        issue_action_plan=AsyncMock(side_effect=PermissionError("no channel consent")),
    )
    host.repository = SimpleNamespace(list_personal_owned_connections=AsyncMock())
    with pytest.raises(PermissionError, match="no channel consent"):
        await host.inspect_owned_channel_connections(
            tenant_id=TENANT, user_id=USER, session_id="plugin-session",
            request_id="plugin-request", correlation_id="plugin-correlation",
            installation_id="telegram-bot",
        )
    host.repository.list_personal_owned_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_channel_summary_rejects_cross_tenant_ledger_evidence():
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.host import ChannelHostServices

    host = object.__new__(ChannelHostServices)
    host._initialized, host._closed = True, False
    host._installed = {"telegram-bot": object()}
    host.kernel = SimpleNamespace(get_channel_activation_manifest=lambda name: object())
    host.activation = SimpleNamespace(issue_action_plan=AsyncMock())
    foreign = ChannelConnection(
        connection_id="foreign-conn", tenant_id="foreign-tenant",
        installation_id="telegram-bot", provider_account_id="foreign",
        credential_handle="vault://foreign", revision=2, enabled=True,
    )
    host.repository = SimpleNamespace(
        list_personal_owned_connections=AsyncMock(return_value=[foreign]),
    )
    with pytest.raises(PermissionError, match="Cross-tenant"):
        await host.inspect_owned_channel_connections(
            tenant_id=TENANT, user_id=USER, session_id="plugin-session",
            request_id="plugin-request", correlation_id="plugin-correlation",
            installation_id="telegram-bot",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_status,owned,enabled,phrase", [
    ("none_owned", 0, 0, "No personal channel connection"),
    ("owned_enabled_recorded", 1, 1, "recorded as enabled"),
    ("owned_disabled_recorded", 1, 0, "recorded as disabled"),
])
async def test_runtime_merges_only_owner_authorized_status_without_claiming_delivery(
    connection_status, owned, enabled, phrase,
):
    from ai_karen_engine.services.channels.host import ChannelHostServices

    host = object.__new__(ChannelHostServices)
    host.inspect_owned_channel_connections = AsyncMock(return_value={
        "inspection_source": "tenant_scoped_channel_owner_ledger",
        "owned_connection_count": owned,
        "persisted_enabled_count": enabled,
        "connection_status": connection_status,
        "provider_registration_verified": False,
        "runtime_execution_verified": False,
        "provider_delivery_verified": False,
    })
    executor = DirectCapabilityExecutor()
    executor.bind_channel_host(host)
    service = _catalog()
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=service,
    ):
        result = await executor.execute(
            request=_request("Is my Telegram connected?"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert phrase in result.text
    assert "not verified" in result.text
    plugin = result.payload["plugin_inspection"]["matches"][0]
    assert plugin["connection_status"] == connection_status
    assert plugin["provider_delivery_verified"] is False
    assert result.payload["requested_action_executed"] is False
    host.inspect_owned_channel_connections.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, session_id="plugin-session",
        request_id="plugin-request", correlation_id="plugin-correlation",
        installation_id="telegram-bot",
    )


@pytest.mark.asyncio
async def test_denied_channel_owner_status_does_not_expose_private_reason():
    from ai_karen_engine.services.channels.host import ChannelHostServices

    host = object.__new__(ChannelHostServices)
    host.inspect_owned_channel_connections = AsyncMock(
        side_effect=PermissionError("private principal detail"),
    )
    executor = DirectCapabilityExecutor()
    executor.bind_channel_host(host)
    plan = _plan()
    with patch(
        "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
        return_value=_catalog(),
    ):
        result = await executor.execute(
            request=_request("Set up my Telegram"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert "inspection was denied" in result.text
    assert "private principal detail" not in result.text
    plugin = result.payload["plugin_inspection"]["matches"][0]
    assert plugin["connection_status"] == "inspection_denied"
    assert plugin.get("owned_connection_count") is None


def test_channel_host_binding_refuses_untrusted_plugin_provided_host():
    with pytest.raises(TypeError):
        DirectCapabilityExecutor().bind_channel_host(SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.parametrize("action,role,status", [
    ("disable", "admin", "needs_explicit_confirmation"),
    ("enable", "admin", "already_satisfied"),
    ("disable", "user", "permission_denied"),
    ("install", "admin", "unsupported_action"),
    ("uninstall", "admin", "unsupported_action"),
])
async def test_global_plugin_management_preflight_requires_exact_admin_permission(
    action, role, status,
):
    from ai_karen_engine.auth.rbac_middleware import Permission

    service = _catalog()
    service.enable_plugin = AsyncMock()
    service.disable_plugin = AsyncMock()
    principal = UserData(user_id=USER, tenant_id=TENANT, roles=[role])
    gate = SimpleNamespace(
        has_permission=lambda user, permission: (
            role == "admin" and permission is Permission.ADMIN_PLUGINS_MANAGE
            and user is principal
        ),
    )
    with patch(
        "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
        return_value=gate,
    ):
        plan = await service.preview_conversational_management(
            plugin_id="timezone-clock", action=action, principal=principal,
        )
    assert plan["status"] == status
    assert plan["operation_scope"] == "application_global"
    assert plan["required_permission"] == Permission.ADMIN_PLUGINS_MANAGE.value
    assert plan["approval_granted"] is False
    assert plan["mutation_performed"] is False
    assert plan["action_receipt"] is None
    if status == "needs_explicit_confirmation":
        assert plan["permission_verified"] is True
        assert plan["next_action"] == "plugin.open_admin_management"
        assert plan["confirmation_channel"] == "authenticated_plugin_management_ui"
    service.enable_plugin.assert_not_awaited()
    service.disable_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_lifecycle_cannot_use_generic_plugin_management():
    service = _catalog()
    service.enable_plugin = AsyncMock()
    service.disable_plugin = AsyncMock()
    principal = UserData(user_id=USER, tenant_id=TENANT, roles=["admin"])
    with patch(
        "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
    ) as rbac:
        plan = await service.preview_conversational_management(
            plugin_id="telegram-bot", action="enable", principal=principal,
        )
    assert plan["status"] == "delegated_to_channel_host"
    assert plan["next_action"] == "channel.inspect_and_request_operator_authorization"
    assert plan["mutation_performed"] is False
    rbac.assert_not_called()
    service.enable_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_management_preflight_fails_closed_for_unverified_or_forged_principal():
    service = _catalog()
    for principal in (
        UserData(user_id="", tenant_id=TENANT, roles=["admin"]),
        UserData(user_id=USER, tenant_id="", roles=["admin"]),
        UserData(user_id=USER, tenant_id=TENANT, roles=["admin"], is_verified=False),
        UserData(user_id=USER, tenant_id=TENANT, roles=["admin"], is_active=False),
        {"user_id": USER, "tenant_id": TENANT, "roles": ["admin"]},
    ):
        with pytest.raises(PermissionError):
            await service.preview_conversational_management(
                plugin_id="timezone-clock", action="disable",
                principal=principal,
            )


@pytest.mark.asyncio
async def test_admin_conversational_manage_returns_actionable_preview_without_mutation():
    from ai_karen_engine.auth.rbac_middleware import Permission

    service = _catalog()
    service.disable_plugin = AsyncMock()
    request = _request("Disable my Timezone Clock plugin", roles=["admin"])
    plan = _plan()
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=service,
        ),
        patch(
            "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
            return_value=SimpleNamespace(
                has_permission=lambda user, perm: (
                    perm is Permission.ADMIN_PLUGINS_MANAGE
                    and "admin" in user.roles
                ),
            ),
        ),
    ):
        result = await DirectCapabilityExecutor().execute(
            request=request,
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success and result.source == "plugin_catalog"
    assert "authenticated Plugins & Tools management" in result.text
    assert "did not perform" in result.text
    assert result.payload["requested_action_executed"] is False
    assert result.payload["next_action"] == "plugin.open_admin_management"
    preview = result.payload["plugin_management_preflight"]
    assert preview["status"] == "needs_explicit_confirmation"
    assert preview["permission_verified"] is True
    assert preview["approval_granted"] is False
    assert preview["action_receipt"] is None
    assert result.normalized_metadata()["structured_content"]["plugin_management_preflight"] == preview
    service.disable_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_admin_manage_does_not_surface_confirmation_action():
    from ai_karen_engine.auth.rbac_middleware import Permission

    service = _catalog()
    plan = _plan()
    with (
        patch(
            "ai_karen_engine.core.runtime.direct_capability_executor.get_plugin_service",
            return_value=service,
        ),
        patch(
            "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
            return_value=SimpleNamespace(
                has_permission=lambda user, perm: False,
            ),
        ),
    ):
        result = await DirectCapabilityExecutor().execute(
            request=_request("Disable my Timezone Clock plugin"),
            decision=SimpleNamespace(intent="plugin.inspect"),
            plan=plan, meter=_meter(plan),
        )
    assert result.success
    assert "not authorized" in result.text
    assert result.payload["requested_action_executed"] is False
    assert result.payload["plugin_management_preflight"]["status"] == "permission_denied"
    assert result.payload["next_action"] is None
