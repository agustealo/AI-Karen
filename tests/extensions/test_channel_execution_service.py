"""KOC-04B: claimed external events execute only as verified ChatRuntime turns."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionStatus,
)
from ai_karen_engine.persistence.repositories.channel_repository import (
    ClaimedChannelMessage,
)
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels.execution import (
    ChannelClaimLost,
    ChannelExecutionDenied,
    ChannelExecutionService,
    _stable_channel_session,
)


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
INBOX = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TOKEN = "dddddddd-dddd-dddd-dddd-dddddddddddd"
BINDING = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
CORRELATION = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def claimed():
    return ClaimedChannelMessage(
        inbox_id=INBOX,
        correlation_id=CORRELATION,
        tenant_id=TENANT,
        user_id=USER,
        binding_id=BINDING,
        connection_id="connection-1",
        external_conversation_id="native-conversation",
        external_sender_id="native-sender",
        message_kind="text",
        text="Hello Karen",
    )


def principal(*, active=True, tenant_id=TENANT):
    return SimpleNamespace(
        id=USER,
        tenant_id=tenant_id,
        status=UserStatus.ACTIVE if active else UserStatus.LOCKED,
        roles=["user"],
    )


def components(*, response_source="model", degraded=False, active=True, scope=TENANT):
    repo = SimpleNamespace(
        load_claimed_message=AsyncMock(return_value=claimed()),
        renew_inbound_claim=AsyncMock(return_value=True),
        complete_and_stage_delivery=AsyncMock(return_value=True),
        fail_inbound_claim=AsyncMock(return_value=True),
    )
    runtime = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(
            answer="Hello from ChatRuntime",
            status=ChatExecutionStatus.OK,
            metadata=SimpleNamespace(to_dict=lambda: {
                "response_source": response_source,
                "degraded_mode": degraded,
            }),
        ))
    )
    lookup = AsyncMock(return_value=principal(active=active, tenant_id=scope))
    service = ChannelExecutionService(
        repository=repo, chat_runtime=runtime, principal_lookup=lookup
    )
    return service, repo, runtime, lookup


@pytest.mark.asyncio
async def test_claimed_message_executes_through_chat_runtime_and_stages_outbox(monkeypatch):
    service, repo, runtime, lookup = components()

    async def execute_without_timer(operation, *, renew, heartbeat_seconds,
                                   lost_error, lost_message):
        assert heartbeat_seconds >= 1.0
        assert await renew() is True
        return await operation

    monkeypatch.setattr(
        "ai_karen_engine.services.channels.execution.run_with_claim_heartbeat",
        execute_without_timer,
    )
    success = await service.execute_claimed_text(
        tenant_id=TENANT, inbox_id=INBOX,
        claim_token=TOKEN, lease_seconds=90,
    )

    assert success is True
    lookup.assert_awaited_once_with(tenant_id=TENANT, user_id=USER)
    runtime.execute.assert_awaited_once()
    request = runtime.execute.await_args.args[0]
    assert request.context.tenant_id == TENANT
    assert request.context.user_id == USER
    assert request.context.request_id == INBOX
    assert request.context.correlation_id == CORRELATION
    assert request.context.permissions == []
    assert request.messages == [{"role": "user", "content": "Hello Karen"}]
    assert request.metadata["transport"] == "communication_channel"
    assert request.context.session_id == _stable_channel_session(claimed())
    assert repo.complete_and_stage_delivery.await_count == 1
    delivery = repo.complete_and_stage_delivery.await_args.kwargs["delivery"]
    assert delivery.message_kind == "text"
    assert delivery.text == "Hello from ChatRuntime"
    assert delivery.idempotency_key == INBOX
    assert delivery.destination_id == "native-conversation"
    repo.fail_inbound_claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_principal_never_calls_chat_runtime():
    service, repo, runtime, _ = components(active=False)
    with pytest.raises(ChannelExecutionDenied):
        await service._process(tenant_id=TENANT, inbox_id=INBOX, claim_token=TOKEN)
    runtime.execute.assert_not_awaited()
    repo.complete_and_stage_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_principal_never_calls_chat_runtime():
    service, repo, runtime, _ = components(scope="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    with pytest.raises(ChannelExecutionDenied):
        await service._process(tenant_id=TENANT, inbox_id=INBOX, claim_token=TOKEN)
    runtime.execute.assert_not_awaited()
    repo.complete_and_stage_delivery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source,degraded", [
    ("unavailable", False),
    (None, False),
    ("model", True),
])
async def test_non_model_or_degraded_response_cannot_be_staged(source, degraded):
    service, repo, _, _ = components(response_source=source, degraded=degraded)
    with pytest.raises(ChannelExecutionDenied):
        await service._process(tenant_id=TENANT, inbox_id=INBOX, claim_token=TOKEN)
    repo.complete_and_stage_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_claim_after_chat_does_not_send_or_publish():
    service, repo, runtime, _ = components()
    repo.complete_and_stage_delivery.return_value = False
    with pytest.raises(ChannelClaimLost):
        await service._process(tenant_id=TENANT, inbox_id=INBOX, claim_token=TOKEN)
    runtime.execute.assert_awaited_once()


def test_stable_session_is_tenant_and_principal_scoped():
    item = claimed()
    scope = _stable_channel_session(item)
    assert scope == _stable_channel_session(item)
    assert scope != _stable_channel_session(
        replace(item, user_id="22222222-2222-2222-2222-222222222222")
    )
