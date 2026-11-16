"""Managed WhatsApp Cloud adapter contracts: signed admission, safe provider truth."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection, ChannelDeliveryRequest, ChannelDeliveryState,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
APP_SECRET = "app-secret-with-sufficient-entropy"
TOKEN = "host-scoped-whatsapp-access-token-12345"
PHONE = "10987654321"


def adapter_components(*, status=200, reply=None):
    root = Path(__file__).resolve().parents[2] / "src/ai_karen_engine/extensions/plugins"
    kernel = PluginKernel(root)
    adapter = kernel.loader.load_extension("whatsapp-cloud")
    resolver = AsyncMock(return_value={
        "app_secret": APP_SECRET,
        "access_token": TOKEN,
        "phone_number_id": PHONE,
        "graph_api_version": "v23.0",
    })
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
        status, json=reply if reply is not None else {
            "messaging_product": "whatsapp",
            "messages": [{"id": "wamid.provider-receipt-42"}],
            "contacts": [{"wa_id": "15551234567"}],
        },
    )))
    adapter.bind_host_services(secret_resolver=resolver, http_client=client)
    account = ChannelConnection(
        connection_id="wa-1", installation_id="whatsapp-cloud",
        tenant_id=TENANT, provider_account_id=PHONE,
        credential_handle="vault://whatsapp-one", revision=1, enabled=True,
    )
    return kernel, adapter, account, resolver, client


def signed_message():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": PHONE},
            "messages": [{"id": "wamid.event-42", "from": "15551234567",
                          "type": "text", "text": {"body": "Hi Karen"}}],
        }}]}],
    }).encode()
    signature = "sha256=" + hmac.new(
        APP_SECRET.encode(), body, hashlib.sha256,
    ).hexdigest()
    return body, {"X-Hub-Signature-256": signature}


def delivery():
    return ChannelDeliveryRequest(
        delivery_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        connection_id="wa-1", destination_id="15551234567",
        idempotency_key="wamid.event-42", message_kind="text",
        text="Hello from Karen",
    )


@pytest.mark.asyncio
async def test_disabled_whatsapp_plugin_cannot_run_without_host_activation():
    kernel, adapter, account, _, client = adapter_components()
    manifest = kernel.loader.load_manifest("whatsapp-cloud")
    assert manifest.rbac.default_enabled is False
    assert manifest.capabilities.communication_channel.inbound == ["text"]
    with pytest.raises(PermissionError):
        await adapter.send(connection=account, delivery=delivery())
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_whatsapp_text_is_host_untrusted_identity_only():
    _, adapter, account, _, _ = adapter_components()
    await adapter.start(connection=account)
    body, headers = signed_message()
    assert await adapter.verify_event(connection=account, headers=headers, body=body)
    event = await adapter.normalize_event(connection=account, headers=headers, body=body)
    assert (event.external_sender_id, event.external_conversation_id) == (
        "15551234567", "15551234567",
    )
    assert event.text == "Hi Karen"
    assert not hasattr(event, "user_id")
    assert not hasattr(event, "tenant_id")
    assert not await adapter.verify_event(
        connection=account, headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        body=body,
    )


@pytest.mark.asyncio
async def test_provider_message_id_is_required_to_mark_whatsapp_sent():
    _, adapter, account, _, client = adapter_components()
    await adapter.start(connection=account)
    receipt = await adapter.send(connection=account, delivery=delivery())
    assert receipt.state is ChannelDeliveryState.SENT
    assert receipt.provider_message_id == "wamid.provider-receipt-42"
    assert client.post.await_args.kwargs["json"]["to"] == "15551234567"


@pytest.mark.asyncio
async def test_http_429_cannot_claim_success_or_retry():
    _, adapter, account, _, client = adapter_components(status=429)
    await adapter.start(connection=account)
    receipt = await adapter.send(connection=account, delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_account_and_mismatched_provider_receipt_fail_closed():
    _, adapter, account, _, client = adapter_components(reply={
        "messaging_product": "whatsapp",
        "messages": [{"id": "wamid.provider-receipt-42"}],
        "contacts": [{"wa_id": "9999999"}],
    })
    await adapter.start(connection=account)
    assert (await adapter.send(
        connection=account, delivery=delivery(),
    )).state is ChannelDeliveryState.UNKNOWN
    other = account.model_copy(update={"tenant_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"})
    with pytest.raises(PermissionError):
        await adapter.send(connection=other, delivery=delivery())
    assert client.post.await_count == 1


def test_whatsapp_manifest_projects_backend_only_channel_not_ui():
    """An installed channel must never be treated as a missing UI package."""
    from ai_karen_engine.extensions.platform.core.manager import ExtensionCoreManager

    kernel, _adapter, _account, _resolver, _client = adapter_components()
    manifest = kernel.loader.load_manifest("whatsapp-cloud")
    projected = ExtensionCoreManager._extension_capabilities(manifest)
    assert projected["communication_channel"] is True
    assert projected["provides_ui"] is False
    assert projected["provides_webhooks"] is True

    from ai_karen_engine.api_routes.extensions.extensions import ExtensionStatusAPI

    serialized = ExtensionStatusAPI.model_validate(
        ExtensionCoreManager._status_from_record({
            "manifest": manifest, "status": "disabled",
        })
    ).model_dump()
    assert serialized["status"] == "disabled"
    assert serialized["capabilities"]["communication_channel"] is True
    assert serialized["capabilities"]["provides_ui"] is False


def test_non_channel_manifest_does_not_claim_transport_authority():
    from types import SimpleNamespace

    from ai_karen_engine.extensions.platform.core.manager import ExtensionCoreManager

    generic = SimpleNamespace(capabilities=SimpleNamespace(
        provides_ui=True,
        provides_api=False,
        provides_webhooks=False,
        provides_background_tasks=False,
        communication_channel=None,
    ))
    assert ExtensionCoreManager._extension_capabilities(generic) == {
        "provides_ui": True,
        "provides_api": False,
        "provides_webhooks": False,
        "provides_background_tasks": False,
        "communication_channel": False,
    }


@pytest.mark.asyncio
async def test_meta_subscription_handshake_uses_host_vault_token_and_connection_scope():
    _, adapter, account, resolver, client = adapter_components()
    resolver.return_value = {
        **resolver.return_value,
        "webhook_verify_token": "meta-verify-token-123",
    }
    await adapter.start(connection=account)
    assert await adapter.verify_subscription(
        connection=account, verify_token="meta-verify-token-123",
    ) is True
    assert await adapter.verify_subscription(
        connection=account, verify_token="different-token-123",
    ) is False
    assert await adapter.verify_subscription(
        connection=account, verify_token="\nmeta-verify-token-123",
    ) is False
    assert await adapter.verify_subscription(
        connection=account, verify_token="wrong",
    ) is False
    foreign_account = account.model_copy(update={
        "provider_account_id": "99999999999",
    })
    with pytest.raises(PermissionError):
        await adapter.verify_subscription(
            connection=foreign_account, verify_token="meta-verify-token-123",
        )
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_meta_subscription_does_not_accept_missing_host_secret_or_stale_revision():
    _, adapter, account, resolver, client = adapter_components()
    await adapter.start(connection=account)
    assert await adapter.verify_subscription(
        connection=account, verify_token="meta-verify-token-123",
    ) is False
    stale = account.model_copy(update={"revision": 2})
    with pytest.raises(PermissionError):
        await adapter.verify_subscription(
            connection=stale, verify_token="meta-verify-token-123",
        )
    resolver.return_value = {
        **resolver.return_value,
        "webhook_verify_token": "meta-verify-token-123",
    }
    wrong_phone = account.model_copy(update={"provider_account_id": "99999999999"})
    adapter._started.add(adapter._key(wrong_phone))
    with pytest.raises(PermissionError, match="credentials"):
        await adapter.verify_subscription(
            connection=wrong_phone, verify_token="meta-verify-token-123",
        )
    client.post.assert_not_awaited()



def signed_batch(payload):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": "sha256=" + hmac.new(
            APP_SECRET.encode(), body, hashlib.sha256,
        ).hexdigest(),
    }
    return body, headers


def webhook_value(*, messages=None, statuses=None, phone=PHONE):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": phone},
    }
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return value


@pytest.mark.asyncio
async def test_signed_whatsapp_batch_normalizes_separate_messages_and_receipts():
    _, adapter, account, resolver, client = adapter_components()
    await adapter.start(connection=account)
    status = {
        "id": "wamid.provider-receipt-42",
        "recipient_id": "15551234567",
        "status": "delivered",
        "timestamp": "1770000000",
    }
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": webhook_value(
                    messages=[
                        {"id": "wamid.first-1", "from": "15551234567",
                         "type": "text", "text": {"body": "First"}},
                        {"id": "wamid.media-1", "from": "15551234567",
                         "type": "image", "image": {"id": "not-for-chat"}},
                    ],
                    statuses=[status],
                ),
            }, {
                "field": "messages",
                "value": webhook_value(messages=[
                    {"id": "wamid.second-2", "from": "15551234567",
                     "type": "text", "text": {"body": "Second"}},
                ]),
            }],
        }],
    }
    body, headers = signed_batch(payload)
    assert await adapter.verify_event(connection=account, headers=headers, body=body)
    batch = await adapter.normalize_events(connection=account, headers=headers, body=body)
    assert tuple(event.text for event in batch.messages) == ("First", "Second")
    assert len(batch.statuses) == 1
    assert batch.ignored_count == 1
    evidence = batch.statuses[0]
    assert evidence.state is ChannelDeliveryState.DELIVERED
    assert evidence.provider_message_id == "wamid.provider-receipt-42"
    assert evidence.recipient_id == "15551234567"
    assert evidence.provider_timestamp == 1770000000
    assert len(evidence.provider_receipt_id) == 64
    assert not hasattr(evidence, "user_id")
    assert not hasattr(evidence, "tenant_id")
    client.post.assert_not_awaited()
    resolver.assert_awaited()


@pytest.mark.asyncio
async def test_status_only_callback_is_not_a_chat_message():
    _, adapter, account, _, _ = adapter_components()
    await adapter.start(connection=account)
    body, headers = signed_batch({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": webhook_value(
            statuses=[{
                "id": "wamid.provider", "recipient_id": "15551234567",
                "status": "read", "timestamp": "1770000001",
            }],
        )}]}],
    })
    assert await adapter.verify_event(connection=account, headers=headers, body=body)
    batch = await adapter.normalize_events(connection=account, headers=headers, body=body)
    assert batch.messages == ()
    assert len(batch.statuses) == 1
    assert batch.statuses[0].state is ChannelDeliveryState.READ
    with pytest.raises(ValueError, match="Single-event"):
        await adapter.normalize_event(connection=account, headers=headers, body=body)


@pytest.mark.asyncio
async def test_signed_batch_wrong_phone_and_malformed_receipts_fail_closed():
    _, adapter, account, _, client = adapter_components()
    await adapter.start(connection=account)
    examples = [
        webhook_value(
            statuses=[{
                "id": "wamid.provider", "recipient_id": "15551234567",
                "status": "delivered", "timestamp": "1770000000",
            }], phone="99999999999",
        ),
        webhook_value(
            statuses=[{
                "id": "wamid.provider", "recipient_id": "nope",
                "status": "delivered", "timestamp": "1770000000",
            }],
        ),
        webhook_value(
            statuses=[{
                "id": "wamid.provider", "recipient_id": "15551234567",
                "status": "delivered", "timestamp": "bad-time",
            }],
        ),
        webhook_value(messages=[
            {"id": "wamid.provider", "from": "15551234567",
             "type": "text", "text": {"body": ""}},
        ]),
    ]
    for value in examples:
        body, headers = signed_batch({
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": value}]}],
        })
        assert await adapter.verify_event(connection=account, headers=headers, body=body)
        with pytest.raises(ValueError):
            await adapter.normalize_events(connection=account, headers=headers, body=body)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_batch_bound_and_duplicate_json_keys_rejected():
    _, adapter, account, _, _ = adapter_components()
    await adapter.start(connection=account)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{
            "field": "messages",
            "value": webhook_value(messages=[
                {"id": f"wamid.{i}", "from": "15551234567",
                 "type": "text", "text": {"body": "hello"}}
                for i in range(101)
            ]),
        }]}],
    }
    body, headers = signed_batch(payload)
    with pytest.raises(ValueError, match="count exceeds limit"):
        await adapter.normalize_events(connection=account, headers=headers, body=body)
    duplicate = (
        b'{"object":"whatsapp_business_account",'
        b'"object":"whatsapp_business_account","entry":[]}'
    )
    with pytest.raises(ValueError, match="Duplicate"):
        await adapter.normalize_events(connection=account, headers={}, body=duplicate)
    assert not await adapter.verify_event(
        connection=account, headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        body=body,
    )
