"""Channel admission verifies provider evidence without granting AI runtime access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    InboundChannelEvent,
)
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
    InboundAdmission,
)
from ai_karen_engine.services.channels.ingress import ChannelIngressService

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def components(*, enabled=True, verified=True, kind="text"):
    connection = ChannelConnection(
        connection_id="connection-a",
        installation_id="plugin-a",
        tenant_id=TENANT,
        provider_account_id="account-a",
        credential_handle="vault://key-a",
        revision=1,
        enabled=enabled,
    )
    event = InboundChannelEvent(
        connection_id="connection-a",
        external_event_id="event-1",
        external_sender_id="sender-1",
        external_conversation_id="chat-1",
        message_kind=kind,
        text="hi",
    )
    adapter = SimpleNamespace(
        verify_event=AsyncMock(return_value=verified),
        normalize_event=AsyncMock(return_value=event),
    )
    admission = InboundAdmission(
        inbox_id="inbox-1",
        correlation_id="corr-1",
        tenant_id=TENANT,
        user_id="user-1",
        binding_id="binding-1",
        inserted=True,
    )
    repository = SimpleNamespace(
        get_enabled_connection=AsyncMock(return_value=connection if enabled else None),
        admit_verified_inbound=AsyncMock(return_value=admission),
    )
    registration = SimpleNamespace(
        state=ExtensionLifecycleState.ENABLED,
        manifest=SimpleNamespace(
            capabilities=[SimpleNamespace(id="communication_channel")],
            metadata={"communication_channel": {"inbound": ["text"]}},
        ),
    )
    kernel = SimpleNamespace(
        runtime_registry=SimpleNamespace(get=lambda _: registration),
    )
    service = ChannelIngressService(
        kernel=kernel, repository=repository, max_native_body_bytes=4096
    )
    return service, adapter, repository, registration


@pytest.mark.asyncio
async def test_verified_event_reaches_host_bound_repository_once():
    service, adapter, repo, _ = components()
    result = await service.verify_and_admit(
        tenant_id=TENANT, connection_id="connection-a",
        adapter=adapter, headers={"X-Signature": "signed"}, body=b"native",
    )
    assert result.user_id == "user-1"
    assert result.inserted is True
    adapter.verify_event.assert_awaited_once()
    adapter.normalize_event.assert_awaited_once()
    repo.admit_verified_inbound.assert_awaited_once()
    assert repo.admit_verified_inbound.await_args.kwargs["event"].external_sender_id == "sender-1"


@pytest.mark.asyncio
async def test_invalid_signature_never_normalizes_or_persists():
    service, adapter, repo, _ = components(verified=False)
    with pytest.raises(ChannelAdmissionDenied, match="verification"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="connection-a",
            adapter=adapter, headers={}, body=b"bad",
        )
    adapter.normalize_event.assert_not_awaited()
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_plugin_never_calls_provider_adapter():
    service, adapter, repo, registration = components()
    registration.state = ExtensionLifecycleState.DISABLED
    with pytest.raises(ChannelAdmissionDenied, match="not enabled"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="connection-a",
            adapter=adapter, headers={}, body=b"payload",
        )
    adapter.verify_event.assert_not_awaited()
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_connection_rejected_before_adapter_call():
    service, adapter, repo, _ = components(enabled=False)
    with pytest.raises(ChannelAdmissionDenied, match="inactive"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="connection-a",
            adapter=adapter, headers={}, body=b"payload",
        )
    adapter.verify_event.assert_not_awaited()
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_undeclared_message_kind_does_not_enter_inbox():
    service, adapter, repo, _ = components(kind="command")
    with pytest.raises(ChannelAdmissionDenied, match="Unsupported"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="connection-a",
            adapter=adapter, headers={}, body=b"payload",
        )
    adapter.verify_event.assert_awaited_once()
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_tenant_is_not_accepted_as_host_connection_tenant():
    service, adapter, repo, _ = components()
    with pytest.raises(ChannelAdmissionDenied, match="outside tenant"):
        await service.verify_and_admit(
            tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            connection_id="connection-a", adapter=adapter, headers={}, body=b"payload",
        )
    adapter.verify_event.assert_not_awaited()
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_body_limit_checked_before_any_io():
    service, adapter, repo, _ = components()
    with pytest.raises(ValueError, match="budget"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="connection-a",
            adapter=adapter, headers={}, body=b"x" * 4097,
        )
    repo.get_enabled_connection.assert_not_awaited()
    adapter.verify_event.assert_not_awaited()
