"""KOC-04G: canonical host dependency lifecycle, no automatic tenant activation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from ai_karen_engine.config.channels import (
    ChannelHostSettings,
    load_channel_host_settings,
)
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.server.application_runtime import (
    initialize_application_channel_host,
    shutdown_application_runtime,
)


def settings(*, enabled=True, secret_types=None):
    return ChannelHostSettings(
        enabled=enabled,
        installations={
            "telegram-bot": frozenset({"bot_token", "webhook_secret"})
            if secret_types is None else secret_types
        } if enabled else {},
        service_principal_id="channel-host-runtime" if enabled else "",
        max_native_body_bytes=65_536,
        http_timeout_seconds=6.0,
    ).validate()


def fake_components(*, valid=True, canonical=True, bind_failure=False):
    adapter = SimpleNamespace(
        bind_host_services=MagicMock(
            side_effect=RuntimeError("host services rejected") if bind_failure else None,
        ),
        initialize=AsyncMock(),
        shutdown=AsyncMock(),
        start=AsyncMock(),
        stop=AsyncMock(),
        send=AsyncMock(),
    )
    kernel = SimpleNamespace(
        initialize=AsyncMock(),
        cleanup=AsyncMock(),
        get_channel_activation_manifest=lambda _: object() if valid else None,
        loader=SimpleNamespace(load_extension=MagicMock(return_value=adapter)),
        is_canonical_channel_adapter=lambda _, obj: canonical and obj is adapter,
    )
    vault = SimpleNamespace(initialize=AsyncMock(), stop=AsyncMock())
    client = SimpleNamespace(aclose=AsyncMock())
    host = ChannelHostServices(
        settings=settings(), kernel=kernel,
        repository=SimpleNamespace(), vault=vault, http_client=client,
    )
    return host, kernel, vault, client, adapter


def test_channel_host_off_by_default(monkeypatch):
    for name in (
        "KAREN_CHANNEL_HOST_ENABLED",
        "KAREN_CHANNEL_HOST_INSTALLATIONS_JSON",
        "KAREN_CHANNEL_SERVICE_PRINCIPAL_ID",
        "KAREN_CHANNEL_HTTP_TIMEOUT_SECONDS",
        "KAREN_CHANNEL_MAX_BODY_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    actual = load_channel_host_settings()
    assert actual.enabled is False
    assert actual.installations == {}


@pytest.mark.asyncio
async def test_disabled_app_lifecycle_does_not_start_any_channel(monkeypatch):
    monkeypatch.delenv("KAREN_CHANNEL_HOST_ENABLED", raising=False)
    app = FastAPI()
    await initialize_application_channel_host(app)
    assert app.state.channel_ingress_service is None
    assert app.state.channel_host_services is None


def test_personal_pairing_registry_is_explicit_and_requires_signing_secret(monkeypatch):
    monkeypatch.setenv("KAREN_CHANNEL_HOST_ENABLED", "true")
    monkeypatch.setenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", "channel-host-runtime")
    monkeypatch.setenv(
        "KAREN_CHANNEL_HOST_INSTALLATIONS_JSON",
        '{"telegram-bot":["webhook_secret","bot_token"]}',
    )
    monkeypatch.delenv("KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON", raising=False)
    assert load_channel_host_settings().personal_pairing_providers == {}
    monkeypatch.setenv(
        "KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON",
        '{"telegram-bot":"managed-operator"}',
    )
    with pytest.raises(ValueError, match="signing secret"):
        load_channel_host_settings()
    monkeypatch.setenv(
        "KAREN_CHANNEL_HOST_INSTALLATIONS_JSON",
        '{"telegram-bot":["webhook_secret","bot_token","pairing_webhook_secret"]}',
    )
    actual = load_channel_host_settings()
    assert actual.personal_pairing_providers == {"telegram-bot": "managed-operator"}
    monkeypatch.setenv(
        "KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON",
        '{"not-installed":"managed-operator"}',
    )
    with pytest.raises(ValueError, match="signing secret"):
        load_channel_host_settings()


def test_enabled_host_needs_configured_operator_and_transport_registry(monkeypatch):
    monkeypatch.setenv("KAREN_CHANNEL_HOST_ENABLED", "true")
    monkeypatch.setenv("KAREN_CHANNEL_HOST_INSTALLATIONS_JSON", "{}")
    monkeypatch.setenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", "")
    with pytest.raises(ValueError):
        load_channel_host_settings()
    monkeypatch.setenv(
        "KAREN_CHANNEL_HOST_INSTALLATIONS_JSON",
        '{"telegram-bot":["webhook_secret","bot_token"]}',
    )
    monkeypatch.setenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", "channel-host-runtime")
    actual = load_channel_host_settings()
    assert actual.enabled is True
    assert actual.installations == {
        "telegram-bot": frozenset({"webhook_secret", "bot_token"})
    }


@pytest.mark.parametrize("bad_json", [
    '{"telegram-bot":["webhook_secret","webhook_secret"]}',
    '{"telegram-bot":["webhook_secret"],"telegram-bot":["bot_token"]}',
    '{"bad/path":["webhook_secret"]}',
    '{"telegram-bot":[]}',
    '{"telegram-bot":[""]}',
    '{"telegram-bot": ["bot_token", 7]}',
    '[]',
    '{',
])
def test_invalid_installation_registry_refuses_startup(monkeypatch, bad_json):
    monkeypatch.setenv("KAREN_CHANNEL_HOST_ENABLED", "true")
    monkeypatch.setenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", "channel-host-runtime")
    monkeypatch.setenv("KAREN_CHANNEL_HOST_INSTALLATIONS_JSON", bad_json)
    with pytest.raises(ValueError):
        load_channel_host_settings()


@pytest.mark.parametrize("bad", ["maybe", "enabled", "unknown"])
def test_invalid_boolean_flag_is_not_treated_as_disabled(monkeypatch, bad):
    monkeypatch.setenv("KAREN_CHANNEL_HOST_ENABLED", bad)
    with pytest.raises(ValueError, match="boolean"):
        load_channel_host_settings()


@pytest.mark.asyncio
async def test_host_binds_canonical_adapter_and_never_auto_starts_tenant_connection():
    host, kernel, vault, client, adapter = fake_components()
    await host.initialize()
    await host.initialize()  # idempotent
    kernel.initialize.assert_awaited_once()
    vault.initialize.assert_awaited_once()
    adapter.initialize.assert_awaited_once()
    assert host.ingress is not None
    assert host.activation is not None
    assert host.delivery is not None
    assert host.execution is None  # No runtime injected in this isolated test.
    assert host.worker is None
    assert host.ingress.max_native_body_bytes == 65_536
    assert adapter.bind_host_services.call_count == 1
    bound = adapter.bind_host_services.call_args.kwargs
    assert bound["http_client"] is client
    assert bound["secret_resolver"]._installation_id == "telegram-bot"
    assert bound["secret_resolver"]._required_secret_types == frozenset(
        {"webhook_secret", "bot_token"}
    )
    adapter.start.assert_not_awaited()
    adapter.send.assert_not_awaited()
    await host.shutdown()
    await host.shutdown()  # no second stop
    adapter.shutdown.assert_awaited_once()
    vault.stop.assert_awaited_once()
    kernel.cleanup.assert_awaited_once()
    client.aclose.assert_awaited_once()
    assert host.ingress is None and host.activation is None
    assert host.execution is None and host.delivery is None
    assert host.worker is None


@pytest.mark.asyncio
async def test_wrong_or_disabled_catalog_fails_before_bind_and_closes_owned_resources():
    host, kernel, vault, client, adapter = fake_components(valid=False)
    with pytest.raises(RuntimeError, match="unavailable"):
        await host.initialize()
    adapter.bind_host_services.assert_not_called()
    adapter.start.assert_not_awaited()
    kernel.cleanup.assert_awaited_once()
    vault.stop.assert_awaited_once()
    client.aclose.assert_awaited_once()
    assert host.ingress is None


@pytest.mark.asyncio
async def test_noncanonical_adapter_is_rejected_without_start():
    host, _, _, client, adapter = fake_components(canonical=False)
    with pytest.raises(RuntimeError, match="canonical"):
        await host.initialize()
    adapter.start.assert_not_awaited()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_host_bind_cannot_leave_http_client_or_transport_running():
    host, _, _, client, adapter = fake_components(bind_failure=True)
    with pytest.raises(RuntimeError, match="host services rejected"):
        await host.initialize()
    adapter.start.assert_not_awaited()
    adapter.send.assert_not_awaited()
    client.aclose.assert_awaited_once()
    assert host.ingress is None


@pytest.mark.asyncio
async def test_host_shutdown_does_not_destroy_services_it_borrowed():
    host, kernel, vault, client, adapter = fake_components()
    host._owns_kernel = False
    host._owns_vault = False
    await host.initialize()
    await host.shutdown()
    kernel.cleanup.assert_not_awaited()
    vault.stop.assert_not_awaited()
    adapter.shutdown.assert_awaited_once()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_credential_authorizer_denies_unconfigured_installation_and_stopped_host():
    host, _, _, _, _ = fake_components()
    await host.initialize()
    assert not await host.authorize_reference(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        installation_id="unregistered-transport",
        credential_handle="vault://cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    await host.shutdown()
    assert not await host.authorize_reference(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        installation_id="telegram-bot",
        credential_handle="vault://cccccccc-cccc-cccc-cccc-cccccccccccc",
    )


@pytest.mark.asyncio
async def test_application_shutdown_revokes_ingress_before_database_cleanup(monkeypatch):
    app = FastAPI()
    seen = []
    async def stop():
        assert app.state.channel_ingress_service is None
        seen.append("channel_stopped")
    fake_host = SimpleNamespace(shutdown=AsyncMock(side_effect=stop))
    app.state.channel_ingress_service = object()
    app.state.channel_host_services = fake_host
    app.state.model_download_worker = None
    app.state.chat_runtime_control_plane = None
    app.state._canonical_runtime_shutdown = False
    # Stub the database config import used by the existing final shutdown path
    # without changing runtime routing or model selection.
    from ai_karen_engine.services.database import database_config
    monkeypatch.setattr(
        database_config,
        "get_database_config",
        lambda *_: SimpleNamespace(cleanup=AsyncMock(side_effect=lambda: seen.append("db"))),
    )
    await shutdown_application_runtime(app)
    assert seen == ["channel_stopped", "db"]
    assert app.state.channel_host_services is None
    fake_host.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_host_binds_existing_runtime_execution_without_starting_worker():
    host, _, _, _, adapter = fake_components()
    runtime = SimpleNamespace(execute=AsyncMock())
    host._chat_runtime = runtime
    await host.initialize()
    assert host.execution is not None
    assert host.execution._chat_runtime is runtime
    assert host.worker is not None
    assert host.ingress._on_admitted is not None
    assert host.execution._repository is host.repository
    assert host.delivery is not None
    assert host.delivery._repository is host.repository
    assert host.delivery._kernel is host.kernel
    runtime.execute.assert_not_awaited()
    adapter.start.assert_not_awaited()
    adapter.send.assert_not_awaited()
    await host.shutdown()
    assert host.execution is None
    assert host.delivery is None
    assert host.worker is None


@pytest.mark.asyncio
async def test_explicit_recovery_requires_policy_before_reading_backlog():
    host, _, _, _, _ = fake_components()
    host._chat_runtime = SimpleNamespace(execute=AsyncMock())
    await host.initialize()
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.persistence.repositories.channel_repository import InboundAdmission
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    connection = ChannelConnection(
        connection_id="c1", tenant_id=tenant, installation_id="telegram-bot",
        provider_account_id="account", credential_handle="vault://ref",
        revision=3, enabled=True,
    )
    receipt = InboundAdmission(
        inbox_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        correlation_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        tenant_id=tenant, user_id=user,
        binding_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        inserted=False,
    )
    host.repository.get_enabled_connection = AsyncMock(return_value=connection)
    host.repository.list_recoverable_inbound = AsyncMock(return_value=[receipt])
    host.worker.submit = AsyncMock(return_value=True)
    host.activation._authorize = AsyncMock(side_effect=PermissionError("denied"))
    plan = AuthorizedExecutionPlan(
        execution_id="recovery-1", policy_decision_id="policy-1",
        authorized_user_id=user, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.recover"],
    )
    with pytest.raises(PermissionError, match="denied"):
        await host.recover_inbox(
            tenant_id=tenant, connection_id="c1", user_id=user,
            session_id="session", authorized_plan=plan,
        )
    host.repository.list_recoverable_inbound.assert_not_awaited()
    host.worker.submit.assert_not_awaited()
    host.activation._authorize.side_effect = None
    assert await host.recover_inbox(
        tenant_id=tenant, connection_id="c1", user_id=user,
        session_id="session", authorized_plan=plan,
    ) == 1
    host.activation._authorize.assert_awaited_with(
        tenant_id=tenant, user_id=user, session_id="session",
        installation_id="telegram-bot", action="channel.recover", plan=plan,
    )
    host.repository.list_recoverable_inbound.assert_awaited_once_with(
        tenant_id=tenant, connection_id="c1", limit=100,
    )
    host.worker.submit.assert_awaited_once_with(receipt)
    await host.shutdown()


@pytest.mark.asyncio
async def test_recovery_refuses_disabled_or_cross_tenant_connection_before_policy():
    host, _, _, _, _ = fake_components()
    host._chat_runtime = SimpleNamespace(execute=AsyncMock())
    await host.initialize()
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="c1", tenant_id=other, installation_id="telegram-bot",
        provider_account_id="account", credential_handle="vault://ref",
        revision=3, enabled=True,
    ))
    host.repository.list_recoverable_inbound = AsyncMock()
    host.activation._authorize = AsyncMock()
    with pytest.raises(PermissionError):
        await host.recover_inbox(
            tenant_id=tenant, connection_id="c1", user_id=other,
            session_id="session", authorized_plan=None,
        )
    host.activation._authorize.assert_not_awaited()
    host.repository.list_recoverable_inbound.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_host_dispatch_uses_only_bound_adapter_and_caller_policy_plan():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    host, _, _, _, adapter = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    delivery_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.get_delivery_preflight = AsyncMock(
        return_value=SimpleNamespace(
            connection_id="conn", user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            external_conversation_id="native-room",
        ),
    )
    host.repository.get_enabled_connection = AsyncMock(
        return_value=ChannelConnection(
            connection_id="conn", tenant_id=tenant,
            installation_id="telegram-bot", provider_account_id="account",
            credential_handle="vault://ref", revision=2, enabled=True,
        ),
    )
    host.delivery.dispatch = AsyncMock(return_value=True)
    host.activation._authorize = AsyncMock()
    plan = AuthorizedExecutionPlan(
        execution_id="delivery-1", policy_decision_id="policy-1",
        authorized_user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        authorized_tenant_id=tenant, allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.send"],
    )
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    user_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    session_id = ChannelDeliveryService._session_id(
        tenant_id=tenant, user_id=user_id, connection_id="conn",
        external_conversation_id="native-room",
    )
    assert await host.dispatch_outbox(
        tenant_id=tenant, delivery_id=delivery_id, user_id=user_id,
        session_id=session_id, authorized_plan=plan, lease_seconds=45,
    )
    host.activation._authorize.assert_awaited_once_with(
        tenant_id=tenant, user_id=user_id, session_id=session_id,
        installation_id="telegram-bot", action="channel.send", plan=plan,
    )
    host.delivery.dispatch.assert_awaited_once_with(
        tenant_id=tenant, delivery_id=delivery_id, adapter=adapter,
        authorized_plan=plan, lease_seconds=45,
    )
    adapter.send.assert_not_awaited()
    await host.shutdown()
    with pytest.raises(PermissionError):
        await host.dispatch_outbox(
            tenant_id=tenant, delivery_id=delivery_id,
            user_id=user_id, session_id=session_id, authorized_plan=plan,
        )


@pytest.mark.asyncio
async def test_host_outbound_denies_before_dispatch_when_plan_missing_or_connection_foreign():
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    host, _, _, _, adapter = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.get_delivery_preflight = AsyncMock(
        return_value=SimpleNamespace(
            connection_id="conn", user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            external_conversation_id="native-room",
        ),
    )
    host.repository.get_enabled_connection = AsyncMock(
        return_value=ChannelConnection(
            connection_id="conn", tenant_id=other,
            installation_id="telegram-bot", provider_account_id="account",
            credential_handle="vault://ref", revision=2, enabled=True,
        ),
    )
    host.delivery.dispatch = AsyncMock()
    with pytest.raises(PermissionError, match="plan"):
        await host.dispatch_outbox(
            tenant_id=tenant, delivery_id=other,
            user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            session_id="wrong", authorized_plan=None,
        )
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    plan = AuthorizedExecutionPlan(
        execution_id="delivery-2", policy_decision_id="policy-2",
        authorized_user_id=other, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"],
    )
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    session_id = ChannelDeliveryService._session_id(
        tenant_id=tenant,
        user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        connection_id="conn", external_conversation_id="native-room",
    )
    with pytest.raises(PermissionError, match="connection"):
        await host.dispatch_outbox(
            tenant_id=tenant, delivery_id=other,
            user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            session_id=session_id, authorized_plan=plan,
        )
    host.delivery.dispatch.assert_not_awaited()
    adapter.send.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_host_outbound_denies_foreign_principal_and_session_before_policy():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    host, _, _, _, adapter = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        connection_id="conn", user_id=user, external_conversation_id="native-room",
    ))
    host.repository.get_enabled_connection = AsyncMock()
    host.activation._authorize = AsyncMock()
    host.delivery.dispatch = AsyncMock()
    plan = AuthorizedExecutionPlan(
        execution_id="delivery-3", policy_decision_id="policy-3",
        authorized_user_id=user, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"], allowed_capabilities=["channel.send"],
    )
    with pytest.raises(PermissionError, match="principal"):
        await host.dispatch_outbox(
            tenant_id=tenant, delivery_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            session_id="anything", authorized_plan=plan,
        )
    with pytest.raises(PermissionError, match="session"):
        await host.dispatch_outbox(
            tenant_id=tenant, delivery_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            user_id=user, session_id="wrong", authorized_plan=plan,
        )
    host.repository.get_enabled_connection.assert_not_awaited()
    host.activation._authorize.assert_not_awaited()
    host.delivery.dispatch.assert_not_awaited()
    adapter.send.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_host_issues_fresh_runtime_policy_before_outbound_dispatch():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    delivery = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    session = ChannelDeliveryService._session_id(
        tenant_id=tenant, user_id=user, connection_id="conn",
        external_conversation_id="chat",
    )
    host.repository.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        connection_id="conn", user_id=user, external_conversation_id="chat",
    ))
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="conn", tenant_id=tenant, installation_id="telegram-bot",
        provider_account_id="account", credential_handle="vault://ref",
        revision=2, enabled=True,
    ))
    plan = AuthorizedExecutionPlan(
        execution_id="exec", policy_decision_id="policy",
        authorized_user_id=user, authorized_tenant_id=tenant,
        authorized_session_id=session, allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.send"],
    )
    host.activation.issue_action_plan = AsyncMock(return_value=plan)
    host.dispatch_outbox = AsyncMock(return_value=True)
    assert await host.dispatch_authorized_outbox(
        tenant_id=tenant, delivery_id=delivery, user_id=user,
        session_id=session,
    )
    host.activation.issue_action_plan.assert_awaited_once_with(
        tenant_id=tenant, user_id=user, session_id=session,
        installation_id="telegram-bot", action="channel.send",
    )
    host.dispatch_outbox.assert_awaited_once_with(
        tenant_id=tenant, delivery_id=delivery, user_id=user,
        session_id=session, authorized_plan=plan, lease_seconds=90,
    )
    host.activation.issue_action_plan.side_effect = PermissionError("RBAC denied")
    host.dispatch_outbox.reset_mock()
    with pytest.raises(PermissionError, match="RBAC denied"):
        await host.dispatch_authorized_outbox(
            tenant_id=tenant, delivery_id=delivery, user_id=user,
            session_id=session,
        )
    host.dispatch_outbox.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_forged_outbound_session_never_triggers_policy_issuance():
    host, _, _, _, _ = fake_components()
    await host.initialize()
    host.repository.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        connection_id="conn", user_id="user", external_conversation_id="chat",
    ))
    host.repository.get_enabled_connection = AsyncMock()
    host.activation.issue_action_plan = AsyncMock()
    with pytest.raises(PermissionError, match="session"):
        await host.dispatch_authorized_outbox(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            delivery_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            user_id="user", session_id="forged",
        )
    host.activation.issue_action_plan.assert_not_awaited()
    host.repository.get_enabled_connection.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_outbox_recovery_authorizes_before_enumeration_and_sends_only_owner():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    session = ChannelDeliveryService._session_id(
        tenant_id=tenant, user_id=user, connection_id="conn",
        external_conversation_id="room",
    )
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="conn", tenant_id=tenant, installation_id="telegram-bot",
        provider_account_id="account", credential_handle="vault://ref",
        enabled=True, revision=3,
    ))
    host.repository.list_unattempted_outbound = AsyncMock(return_value=[
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ])
    host.repository.get_delivery_preflight = AsyncMock(side_effect=[
        SimpleNamespace(connection_id="conn", user_id=user,
                        external_conversation_id="room"),
        SimpleNamespace(connection_id="conn", user_id="foreign",
                        external_conversation_id="room"),
    ])
    plan = AuthorizedExecutionPlan(
        execution_id="e", policy_decision_id="p",
        authorized_user_id=user, authorized_tenant_id=tenant,
        authorized_session_id=session,
        allowed_plugins=["telegram-bot"], allowed_capabilities=["channel.send"],
    )
    host.activation.issue_action_plan = AsyncMock(side_effect=PermissionError("denied"))
    host.dispatch_authorized_outbox = AsyncMock(return_value=True)
    with pytest.raises(PermissionError, match="denied"):
        await host.recover_outbox(
            tenant_id=tenant, connection_id="conn", user_id=user,
            session_id=session,
        )
    host.repository.list_unattempted_outbound.assert_not_awaited()
    host.dispatch_authorized_outbox.assert_not_awaited()
    host.activation.issue_action_plan.side_effect = None
    host.activation.issue_action_plan.return_value = plan
    assert await host.recover_outbox(
        tenant_id=tenant, connection_id="conn", user_id=user,
        session_id=session,
    ) == (2, 1)
    host.dispatch_authorized_outbox.assert_awaited_once_with(
        tenant_id=tenant, delivery_id="11111111-1111-1111-1111-111111111111",
        user_id=user, session_id=session,
    )
    await host.shutdown()


@pytest.mark.asyncio
async def test_outbox_recovery_denies_cross_tenant_connection_before_enumeration():
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    host.repository.get_enabled_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="conn", tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", enabled=True, revision=3,
    ))
    host.repository.list_unattempted_outbound = AsyncMock()
    host.activation.issue_action_plan = AsyncMock()
    with pytest.raises(PermissionError):
        await host.recover_outbox(
            tenant_id=tenant, connection_id="conn", user_id="user",
            session_id="channel-session",
        )
    host.activation.issue_action_plan.assert_not_awaited()
    host.repository.list_unattempted_outbound.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_personal_pairing_consent_requires_current_policy_and_persisted_connection():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PERSONAL_WHATSAPP_CONSENT_VERSION,
    )

    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    account = ChannelConnection(
        connection_id="personal-1", tenant_id=tenant,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    )
    host.repository.get_connection = AsyncMock(return_value=account)
    host.repository.is_personal_connection_owner = AsyncMock(return_value=True)
    host.repository.acknowledge_personal_pairing_risk = AsyncMock(return_value=True)
    host.repository.revoke_personal_pairing_consent = AsyncMock(return_value=True)
    host.activation._authorize = AsyncMock(side_effect=PermissionError("denied"))
    plan = AuthorizedExecutionPlan(
        execution_id="consent-1", policy_decision_id="decision-1",
        authorized_user_id=user, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.consent"],
    )
    values = dict(
        tenant_id=tenant, connection_id="personal-1",
        user_id=user, session_id="session",
        provider_id="approved-operator", authorized_plan=plan,
    )
    with pytest.raises(PermissionError, match="acknowledgement"):
        await host.acknowledge_personal_pairing_risk(
            **values, accepted=False,
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
    host.repository.get_connection.assert_not_awaited()
    with pytest.raises(PermissionError, match="denied"):
        await host.acknowledge_personal_pairing_risk(
            **values, accepted=True,
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
    host.repository.acknowledge_personal_pairing_risk.assert_not_awaited()
    host.activation._authorize.side_effect = None
    assert await host.acknowledge_personal_pairing_risk(
        **values, accepted=True,
        policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
    )
    host.repository.acknowledge_personal_pairing_risk.assert_awaited_once_with(
        tenant_id=tenant, connection_id="personal-1",
        user_id=user, provider_id="approved-operator",
        policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
    )
    # Revocation works on disabled connections and never claims provider unlink.
    assert await host.revoke_personal_pairing_risk(**values)
    host.repository.revoke_personal_pairing_consent.assert_awaited_once_with(
        tenant_id=tenant, connection_id="personal-1",
        user_id=user, provider_id="approved-operator",
    )
    await host.shutdown()


@pytest.mark.asyncio
async def test_personal_pairing_consent_cannot_cross_tenants():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PERSONAL_WHATSAPP_CONSENT_VERSION,
    )

    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.is_personal_connection_owner = AsyncMock(return_value=True)
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="personal-1", tenant_id=other,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    ))
    host.activation._authorize = AsyncMock()
    host.repository.acknowledge_personal_pairing_risk = AsyncMock()
    with pytest.raises(PermissionError, match="not available"):
        await host.acknowledge_personal_pairing_risk(
            tenant_id=tenant, connection_id="personal-1",
            user_id=user, session_id="session", provider_id="approved-operator",
            accepted=True, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
            authorized_plan=AuthorizedExecutionPlan(
                execution_id="consent-2", policy_decision_id="decision-2",
                authorized_user_id=user, authorized_tenant_id=tenant,
                allowed_plugins=["telegram-bot"],
                allowed_capabilities=["channel.consent"],
            ),
        )
    host.activation._authorize.assert_not_awaited()
    host.repository.acknowledge_personal_pairing_risk.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_self_consent_refuses_other_connection_owner_even_with_valid_plan():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection
    from ai_karen_engine.services.channels.personal_pairing_policy import (
        PERSONAL_WHATSAPP_CONSENT_VERSION,
    )

    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="personal-1", tenant_id=tenant,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    ))
    host.repository.is_personal_connection_owner = AsyncMock(return_value=False)
    host.repository.acknowledge_personal_pairing_risk = AsyncMock()
    host.activation._authorize = AsyncMock()
    plan = AuthorizedExecutionPlan(
        execution_id="consent-owner-check", policy_decision_id="decision-owner",
        authorized_user_id=user, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.consent"],
    )
    with pytest.raises(PermissionError, match="connection owner"):
        await host.acknowledge_personal_pairing_risk(
            tenant_id=tenant, connection_id="personal-1",
            user_id=user, session_id="session", provider_id="approved-operator",
            accepted=True, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
            authorized_plan=plan,
        )
    host.activation._authorize.assert_not_awaited()
    host.repository.acknowledge_personal_pairing_risk.assert_not_awaited()
    await host.shutdown()


def test_normal_user_has_consent_but_no_channel_admin_rights():
    from ai_karen_engine.auth.rbac_middleware import (
        Permission, get_rbac_manager,
    )

    permissions = get_rbac_manager().get_user_permissions({
        "user_id": "user-1", "tenant_id": "tenant-1",
        "roles": ["user"], "permissions": [],
    })
    assert Permission.CHANNEL_CONSENT in permissions
    # The deployed shared config, not only Python fallback defaults,
    # must grant self-consent without transport administration.
    from ai_karen_engine.auth.rbac_middleware import ROLE_PERMISSIONS, Role
    assert Permission.CHANNEL_CONSENT in ROLE_PERMISSIONS[Role.USER].permissions
    for forbidden in (
        Permission.CHANNEL_PROVISION, Permission.CHANNEL_ACTIVATE,
        Permission.CHANNEL_DEACTIVATE, Permission.CHANNEL_RECOVER,
        Permission.CHANNEL_SEND,
    ):
        assert forbidden not in permissions


@pytest.mark.asyncio
async def test_only_authorized_operator_can_assign_channel_owner():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    owner = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    operator = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="account-1", tenant_id=tenant,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    ))
    host.repository.assign_personal_connection_owner = AsyncMock(return_value=True)
    host.activation._authorize = AsyncMock(side_effect=PermissionError("denied"))
    plan = AuthorizedExecutionPlan(
        execution_id="assign-owner", policy_decision_id="operator-policy",
        authorized_user_id=operator, authorized_tenant_id=tenant,
        allowed_plugins=["telegram-bot"], allowed_capabilities=["channel.provision"],
    )
    values = dict(
        tenant_id=tenant, connection_id="account-1", owner_user_id=owner,
        operator_user_id=operator, session_id="admin-session",
        authorized_plan=plan,
    )
    with pytest.raises(PermissionError, match="denied"):
        await host.assign_personal_connection_owner(**values)
    host.repository.assign_personal_connection_owner.assert_not_awaited()
    host.activation._authorize.side_effect = None
    assert await host.assign_personal_connection_owner(**values)
    host.activation._authorize.assert_awaited_with(
        tenant_id=tenant, user_id=operator, session_id="admin-session",
        installation_id="telegram-bot", action="channel.provision", plan=plan,
    )
    host.repository.assign_personal_connection_owner.assert_awaited_once_with(
        tenant_id=tenant, connection_id="account-1", user_id=owner,
    )
    await host.shutdown()


@pytest.mark.asyncio
async def test_operator_cannot_assign_owner_to_foreign_connection():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.extensions.channels.contracts import ChannelConnection

    host, _, _, _, _ = fake_components()
    await host.initialize()
    tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    owner = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    operator = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id="account-1",
        tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://ref", revision=1, enabled=False,
    ))
    host.repository.assign_personal_connection_owner = AsyncMock()
    host.activation._authorize = AsyncMock()
    with pytest.raises(PermissionError, match="not available"):
        await host.assign_personal_connection_owner(
            tenant_id=tenant, connection_id="account-1", owner_user_id=owner,
            operator_user_id=operator, session_id="admin-session",
            authorized_plan=AuthorizedExecutionPlan(
                execution_id="foreign-owner", policy_decision_id="policy-foreign",
                authorized_user_id=operator, authorized_tenant_id=tenant,
                allowed_plugins=["telegram-bot"],
                allowed_capabilities=["channel.provision"],
            ),
        )
    host.activation._authorize.assert_not_awaited()
    host.repository.assign_personal_connection_owner.assert_not_awaited()
    await host.shutdown()
