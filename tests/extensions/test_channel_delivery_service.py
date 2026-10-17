"""KOC-04 outbound: never mistake accepted or ambiguous sends for delivery."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryReceipt,
    ChannelDeliveryRequest,
    ChannelDeliveryState,
)
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelDeliveryPreflight,
    ClaimedChannelDelivery,
)
from ai_karen_engine.services.channels.delivery import (
    ChannelDeliveryDenied,
    ChannelDeliveryService,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DELIVERY = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CLAIM = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def create_components(*, state=ChannelDeliveryState.SENT, provider_id="provider-1",
                      adapter_error=None, supports_receipts=False):
    connection = ChannelConnection(
        connection_id="conn", installation_id="channel-plugin",
        tenant_id=TENANT, provider_account_id="account",
        credential_handle="vault://token", revision=3, enabled=True,
    )
    delivery = ChannelDeliveryRequest(
        delivery_id=DELIVERY, connection_id="conn",
        destination_id="native-recipient", idempotency_key="inbox-1",
        message_kind="text", text="ChatRuntime answer",
    )
    claim = ClaimedChannelDelivery(
        connection=connection, delivery=delivery,
        user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        external_conversation_id="native-room",
        claim_token=CLAIM,
    )
    repo = SimpleNamespace(
        get_delivery_preflight=AsyncMock(
            return_value=ChannelDeliveryPreflight(
                connection_id="conn", user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                external_conversation_id="native-room",
            ),
        ),
        get_enabled_connection=AsyncMock(return_value=connection),
        claim_outbound=AsyncMock(return_value=claim),
        renew_outbound_claim=AsyncMock(return_value=True),
        finalize_outbound_claim=AsyncMock(return_value=True),
    )
    registration = SimpleNamespace(
        state=ExtensionLifecycleState.ENABLED,
        manifest=SimpleNamespace(
            capabilities=[SimpleNamespace(id="communication_channel")],
            metadata={"communication_channel": {
                "outbound": ["text"],
                "supports_delivery_receipts": supports_receipts,
            }},
        ),
    )
    kernel = SimpleNamespace(
        runtime_registry=SimpleNamespace(get=lambda _: registration)
    )
    adapter = SimpleNamespace(send=AsyncMock(
        return_value=ChannelDeliveryReceipt(
            delivery_id=DELIVERY, state=state,
            provider_message_id=provider_id,
            provider_receipt_id="provider-receipt-1" if supports_receipts else None,
            error_code="provider_rejected" if state is ChannelDeliveryState.FAILED else None,
        )
    ))
    if adapter_error is not None:
        adapter.send.side_effect = adapter_error
    return ChannelDeliveryService(kernel=kernel, repository=repo), repo, adapter, registration


def authorization(*, user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                  tenant_id=TENANT, allowed=True):
    return AuthorizedExecutionPlan(
        execution_id="channel-send-1",
        policy_decision_id="policy-decision-1",
        authorized_user_id=user_id,
        authorized_tenant_id=tenant_id,
        allowed_plugins=["channel-plugin"] if allowed else [],
    )


@pytest.fixture
def immediate_heartbeat(monkeypatch):
    async def runner(operation, *, renew, heartbeat_seconds, lost_error, lost_message):
        assert await renew()
        return await operation

    monkeypatch.setattr(
        "ai_karen_engine.services.channels.delivery.run_with_claim_heartbeat",
        runner,
    )


@pytest.mark.asyncio
async def test_sent_requires_provider_message_identifier(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization())
    adapter.send.assert_awaited_once()
    receipt = repo.finalize_outbound_claim.await_args.kwargs["receipt"]
    assert receipt.state is ChannelDeliveryState.SENT
    assert receipt.provider_message_id == "provider-1"
    assert repo.claim_outbound.await_count == 1


@pytest.mark.asyncio
async def test_missing_provider_identifier_is_unknown(immediate_heartbeat):
    service, repo, adapter, _ = create_components(provider_id=None)
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    assert repo.finalize_outbound_claim.await_args.kwargs["receipt"].state is ChannelDeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_provider_exception_is_unknown_not_retried(immediate_heartbeat):
    service, repo, adapter, _ = create_components(adapter_error=TimeoutError("network uncertain"))
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    adapter.send.assert_awaited_once()
    receipt = repo.finalize_outbound_claim.await_args.kwargs["receipt"]
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    assert receipt.error_code == "provider_call_uncertain"


@pytest.mark.asyncio
async def test_delivered_without_receipts_capability_is_unknown(immediate_heartbeat):
    service, repo, adapter, _ = create_components(state=ChannelDeliveryState.DELIVERED)
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    assert repo.finalize_outbound_claim.await_args.kwargs["receipt"].state is ChannelDeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_verified_delivery_receipt_is_passed_through(immediate_heartbeat):
    service, repo, adapter, _ = create_components(
        state=ChannelDeliveryState.DELIVERED, supports_receipts=True
    )
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization())
    assert repo.finalize_outbound_claim.await_args.kwargs["receipt"].state is ChannelDeliveryState.DELIVERED


@pytest.mark.asyncio
async def test_disabled_plugin_is_denied_before_claim_or_transport():
    service, repo, adapter, registration = create_components()
    registration.state = ExtensionLifecycleState.DISABLED
    with pytest.raises(ChannelDeliveryDenied, match="not enabled"):
        await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization())
    repo.claim_outbound.assert_not_awaited()
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_rotation_is_not_sent(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    old = await repo.get_enabled_connection()
    repo.get_enabled_connection.side_effect = [
        old, old.model_copy(update={"revision": 4}),
    ]
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    adapter.send.assert_not_awaited()
    receipt = repo.finalize_outbound_claim.await_args.kwargs["receipt"]
    assert receipt.state is ChannelDeliveryState.FAILED
    assert receipt.error_code == "channel_connection_changed"


@pytest.mark.asyncio
async def test_provider_response_for_different_delivery_is_unknown(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    adapter.send.return_value = ChannelDeliveryReceipt(
        delivery_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        state=ChannelDeliveryState.SENT, provider_message_id="foreign-id",
    )
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    assert repo.finalize_outbound_claim.await_args.kwargs["receipt"].state is ChannelDeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_no_pending_delivery_does_not_claim_or_send():
    service, repo, adapter, _ = create_components()
    repo.get_delivery_preflight.return_value = None
    assert await service.dispatch(tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter, authorized_plan=authorization()) is False
    repo.claim_outbound.assert_not_awaited()
    adapter.send.assert_not_awaited()


def test_outbound_sql_claim_is_tenant_scoped_once_and_never_retry_on_expired_lease():
    from inspect import getsource
    from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
    claim = getsource(SqlChannelRepository.claim_outbound)
    assert "o.claim_token IS NULL" in claim
    assert "o.claim_expires_at IS NULL" in claim
    assert "o.status = 'accepted'" in claim
    assert "u.is_active = true" in claim
    assert "c.revision = i.connection_revision" in claim
    assert "b.revoked_at IS NULL" in claim
    expired = getsource(SqlChannelRepository.quarantine_expired_outbound_claims)
    assert "SET status = 'unknown'" in expired
    assert "FOR UPDATE SKIP LOCKED" in expired

@pytest.mark.asyncio
async def test_cross_tenant_plan_denied_without_contacting_provider(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    with pytest.raises(ChannelDeliveryDenied, match="not authorized"):
        await service.dispatch(
            tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter,
            authorized_plan=authorization(tenant_id="22222222-2222-2222-2222-222222222222"),
        )
    adapter.send.assert_not_awaited()
    repo.claim_outbound.assert_not_awaited()
    repo.finalize_outbound_claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_plugin_not_in_authorized_plan_denied(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    with pytest.raises(ChannelDeliveryDenied, match="not authorized"):
        await service.dispatch(
            tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter,
            authorized_plan=authorization(allowed=False),
        )
    adapter.send.assert_not_awaited()
    repo.claim_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_for_other_principal_denied(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    with pytest.raises(ChannelDeliveryDenied, match="not authorized"):
        await service.dispatch(
            tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter,
            authorized_plan=authorization(user_id="22222222-2222-2222-2222-222222222222"),
        )
    adapter.send.assert_not_awaited()
    repo.claim_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_requirement_blocks_automatic_send(immediate_heartbeat):
    service, repo, adapter, _ = create_components()
    plan = authorization()
    plan.approval_requirements = ["human_approval"]
    with pytest.raises(ChannelDeliveryDenied, match="not authorized"):
        await service.dispatch(
            tenant_id=TENANT, delivery_id=DELIVERY, adapter=adapter,
            authorized_plan=plan,
        )
    adapter.send.assert_not_awaited()
    repo.claim_outbound.assert_not_awaited()

@pytest.mark.asyncio
async def test_bound_session_mismatch_cannot_consume_claim():
    service, repo, adapter, _ = create_components()
    plan = authorization()
    plan.authorized_session_id = "wrong-session"
    with pytest.raises(ChannelDeliveryDenied, match="not authorized"):
        await service.dispatch(
            tenant_id=TENANT, delivery_id=DELIVERY,
            adapter=adapter, authorized_plan=plan,
        )
    repo.claim_outbound.assert_not_awaited()
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_timeout_marks_uncertain_without_retries(immediate_heartbeat):
    import asyncio
    service, repo, adapter, _ = create_components()
    async def hang(**kwargs):
        await asyncio.sleep(1000)
    adapter.send.side_effect = hang
    assert await service.dispatch(
        tenant_id=TENANT, delivery_id=DELIVERY,
        adapter=adapter, authorized_plan=authorization(), lease_seconds=3,
    ) is False
    assert adapter.send.await_count == 1
    assert repo.finalize_outbound_claim.await_args.kwargs["receipt"].state is ChannelDeliveryState.UNKNOWN
