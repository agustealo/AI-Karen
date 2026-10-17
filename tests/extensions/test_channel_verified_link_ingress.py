"""Native Telegram link proofs never enter the normal chat inbox."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection, InboundChannelEvent, VerifiedIdentityBinding,
)
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
)
from ai_karen_engine.services.channels.ingress import ChannelIngressService


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TOKEN = "a" * 43
COMMAND = "/link " + TOKEN


def components(*, verified=True, message=COMMAND, canonical=True, active=True):
    connection = ChannelConnection(
        tenant_id=TENANT, connection_id="conn",
        installation_id="telegram-bot", provider_account_id="bot-account",
        credential_handle="vault://telegram", revision=3, enabled=True,
    )
    event = InboundChannelEvent(
        connection_id="conn", external_event_id="741",
        external_sender_id="901", external_conversation_id="901",
        message_kind="text", text=message,
        provider_metadata={"tenant_id": "foreign", "user_id": "forged"},
    )
    expected = VerifiedIdentityBinding(
        tenant_id=TENANT, user_id=USER,
        connection_id="conn", binding_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        external_sender_id="901", revision=1,
    )
    adapter = SimpleNamespace(
        verify_event=AsyncMock(return_value=verified),
        normalize_event=AsyncMock(return_value=event),
    )
    repo = SimpleNamespace(
        get_enabled_connection=AsyncMock(return_value=connection if active else None),
        consume_verified_link=AsyncMock(return_value=expected),
        admit_verified_inbound=AsyncMock(),
    )
    cap = SimpleNamespace(inbound=frozenset(["text"]))
    kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda _: SimpleNamespace(
            capabilities=SimpleNamespace(communication_channel=cap)
        ),
        is_canonical_channel_adapter=lambda plugin_id, obj: canonical,
    )
    service = ChannelIngressService(
        kernel=kernel, repository=repo, max_native_body_bytes=65536,
    )
    return service, repo, adapter, expected


@pytest.mark.asyncio
async def test_native_verified_link_binds_db_user_without_inbox_message():
    service, repo, adapter, expected = components()
    result = await service.verify_and_link(
        tenant_id=TENANT, connection_id="conn", adapter=adapter,
        headers={"X-Telegram-Bot-Api-Secret-Token": "verified-by-adapter"},
        body=b"native-webhook",
    )
    assert result == expected
    kwargs = repo.consume_verified_link.await_args.kwargs
    assert kwargs["external_sender_id"] == "901"
    assert kwargs["proof_digest"] == hashlib.sha256(TOKEN.encode()).hexdigest()
    assert "user_id" not in kwargs and "tenant_id" not in kwargs
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_command_cannot_enter_chat_even_for_already_linked_sender():
    service, repo, adapter, _ = components()
    with pytest.raises(ChannelAdmissionDenied, match="Link proofs"):
        await service.verify_and_admit(
            tenant_id=TENANT, connection_id="conn", adapter=adapter,
            headers={}, body=b"native-webhook",
        )
    repo.admit_verified_inbound.assert_not_awaited()
    repo.consume_verified_link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("verified,canonical,active", [
    (False, True, True), (True, False, True), (True, True, False),
])
async def test_unverified_or_inactive_native_link_rejected_before_db_proof(
    verified, canonical, active,
):
    service, repo, adapter, _ = components(
        verified=verified, canonical=canonical, active=active,
    )
    with pytest.raises(ChannelAdmissionDenied):
        await service.verify_and_link(
            tenant_id=TENANT, connection_id="conn", adapter=adapter,
            headers={}, body=b"native-webhook",
        )
    repo.consume_verified_link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "/link", "/link ",
    "/link short", "/link " + "a" * 42,
    "/link " + "a" * 44,
    "/link " + TOKEN + " extra",
    "/link " + TOKEN + "\nsecond",
    "not a link command",
])
async def test_bad_proof_format_never_attempts_database_identity_link(message):
    service, repo, adapter, _ = components(message=message)
    with pytest.raises(ChannelAdmissionDenied, match="Not an authorized"):
        await service.verify_and_link(
            tenant_id=TENANT, connection_id="conn", adapter=adapter,
            headers={}, body=b"native-webhook",
        )
    repo.consume_verified_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_or_replayed_proof_is_not_accepted():
    service, repo, adapter, _ = components()
    repo.consume_verified_link.return_value = None
    with pytest.raises(ChannelAdmissionDenied, match="expired, used or rejected"):
        await service.verify_and_link(
            tenant_id=TENANT, connection_id="conn", adapter=adapter,
            headers={}, body=b"native-webhook",
        )


@pytest.mark.asyncio
async def test_valid_ordinary_text_still_uses_original_durable_inbox():
    service, repo, adapter, _ = components(message="Hello Karen")
    repo.admit_verified_inbound.return_value = SimpleNamespace(
        tenant_id=TENANT, user_id=USER, inbox_id="inbox",
        correlation_id="correlation", inserted=True,
    )
    admitted = await service.verify_and_admit(
        tenant_id=TENANT, connection_id="conn", adapter=adapter,
        headers={}, body=b"native-webhook",
    )
    assert admitted.inbox_id == "inbox"
    repo.admit_verified_inbound.assert_awaited_once()
    repo.consume_verified_link.assert_not_awaited()
