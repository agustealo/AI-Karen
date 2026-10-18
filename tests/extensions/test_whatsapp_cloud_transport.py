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
