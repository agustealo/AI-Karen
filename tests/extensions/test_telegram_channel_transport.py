"""Telegram reference channel: signed inbound, bounded text, real provider receipts.

This exercises an actually installable ExtensionBase package through Karen's
canonical loader, with offline host-injected secret and network dependencies.
No external API token, tenant fixture, or network account is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryRequest,
    ChannelDeliveryState,
)
from ai_karen_engine.extensions.contracts import (
    RiskClass,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TOKEN = "123456:host-resolved-test-bot-token"
SECRET = "webhook-secret-1"


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2] / (
        "src/ai_karen_engine/extensions/plugins"
    )


def connection(*, enabled=True) -> ChannelConnection:
    return ChannelConnection(
        connection_id="telegram-conn-1",
        installation_id="telegram-bot",
        tenant_id=TENANT,
        provider_account_id="telegram-account",
        credential_handle="vault://telegram-account",
        revision=2,
        enabled=enabled,
    )


def native_message(*, sender=901, chat=901, kind="private", text="Hello Karen"):
    return json.dumps({
        "update_id": 741,
        "tenant_id": "forged-tenant",
        "user_id": "forged-user",
        "message": {
            "message_id": 100,
            "from": {"id": sender},
            "chat": {"id": chat, "type": kind},
            "text": text,
        },
    }).encode("utf-8")


def delivery():
    return ChannelDeliveryRequest(
        delivery_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        connection_id="telegram-conn-1",
        destination_id="901",
        idempotency_key="inbox-event-741",
        message_kind="text",
        text="Hello from Karen",
    )


def load_transport(*, response=None):
    kernel = PluginKernel(_plugin_root())
    adapter = kernel.loader.load_extension("telegram-bot")
    resolver = AsyncMock(return_value={
        "webhook_secret": SECRET,
        "bot_token": TOKEN,
    })
    client = SimpleNamespace(post=AsyncMock(return_value=(
        response if response is not None else httpx.Response(200, json={
            "ok": True,
            "result": {"message_id": 432, "chat": {"id": 901}},
        })
    )))
    adapter.bind_host_services(secret_resolver=resolver, http_client=client)
    return kernel, adapter, resolver, client


@pytest.mark.asyncio
async def test_installed_telegram_channel_is_discoverable_but_disabled():
    kernel, adapter, _, _ = load_transport()
    catalog = kernel.loader.load_manifest("telegram-bot")
    projected = kernel._project_runtime_manifest(catalog)
    assert projected.id == "telegram-bot"
    assert projected.enabled_by_default is False
    assert [c.id for c in projected.capabilities] == ["communication_channel"]
    assert projected.risk_class is RiskClass.HIGH
    assert catalog.capabilities.communication_channel.authentication == "token"
    assert catalog.capabilities.communication_channel.supports_delivery_receipts is False
    assert adapter.manifest.name == "telegram-bot"


@pytest.mark.asyncio
async def test_valid_header_authenticates_exact_native_event_and_leaves_external_user_untrusted():
    _, adapter, resolver, _ = load_transport()
    await adapter.start(connection=connection())
    headers = {"x-tElEgRaM-BoT-aPi-SeCrEt-ToKeN": SECRET}
    body = native_message()
    assert await adapter.verify_event(
        connection=connection(), headers=headers, body=body,
    )
    normalized = await adapter.normalize_event(
        connection=connection(), headers=headers, body=body,
    )
    assert normalized.external_event_id == "741"
    assert normalized.external_sender_id == "901"
    assert normalized.external_conversation_id == "901"
    assert normalized.text == "Hello Karen"
    assert not hasattr(normalized, "tenant_id")
    assert not hasattr(normalized, "user_id")
    resolver.assert_awaited()


@pytest.mark.asyncio
async def test_invalid_or_duplicate_header_fails_closed():
    _, adapter, _, _ = load_transport()
    await adapter.start(connection=connection())
    for headers in (
        {}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        {"X-Telegram-Bot-Api-Secret-Token": SECRET,
         "x-telegram-bot-api-secret-token": SECRET},
    ):
        assert await adapter.verify_event(
            connection=connection(), headers=headers, body=native_message(),
        ) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    native_message(sender=901, chat=-1000999, kind="supergroup"),
    native_message(sender=902, chat=901),
    native_message(text=""),
    json.dumps({"update_id": 74, "edited_message": {"text": "edited"}}).encode(),
])
async def test_unsupported_telegram_updates_do_not_enter_inbox(case):
    _, adapter, _, _ = load_transport()
    await adapter.start(connection=connection())
    with pytest.raises(ValueError):
        await adapter.normalize_event(
            connection=connection(), headers={}, body=case,
        )


@pytest.mark.asyncio
async def test_transport_cannot_start_with_disabled_account():
    _, adapter, _, client = load_transport()
    with pytest.raises(PermissionError):
        await adapter.start(connection=connection(enabled=False))
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_not_bound_blocks_provider_calls():
    kernel = PluginKernel(_plugin_root())
    adapter = kernel.loader.load_extension("telegram-bot")
    with pytest.raises(PermissionError):
        await adapter.start(connection=connection())


@pytest.mark.asyncio
async def test_connection_revision_rotation_must_be_reactivated_by_host():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    rotated = connection().model_copy(update={"revision": 3})
    with pytest.raises(PermissionError, match="not active"):
        await adapter.verify_event(
            connection=rotated,
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
            body=native_message(),
        )
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_scoped_activation_cannot_enable_another_tenant():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    other = connection().model_copy(update={
        "tenant_id": "22222222-2222-2222-2222-222222222222",
    })
    with pytest.raises(PermissionError, match="not active"):
        await adapter.send(connection=other, delivery=delivery())
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_stop_revokes_all_connection_revision_activations():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    await adapter.stop(connection=connection())
    with pytest.raises(PermissionError, match="not active"):
        await adapter.send(connection=connection(), delivery=delivery())
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_requires_actual_bot_api_response_id():
    _, adapter, resolver, client = load_transport()
    await adapter.start(connection=connection())
    receipt = await adapter.send(
        connection=connection(), delivery=delivery(),
    )
    assert receipt.state is ChannelDeliveryState.SENT
    assert receipt.provider_message_id == "432"
    assert receipt.provider_receipt_id is None
    assert client.post.await_count == 1
    args, kwargs = client.post.await_args
    assert args[0].startswith("https://api.telegram.org/bot")
    assert args[0].endswith("/sendMessage")
    assert kwargs["json"] == {"chat_id": 901, "text": "Hello from Karen"}
    assert resolver.await_args.kwargs["tenant_id"] == TENANT
    assert resolver.await_args.kwargs["credential_handle"] == "vault://telegram-account"


@pytest.mark.asyncio
async def test_mismatched_provider_chat_never_reports_sent():
    _, adapter, _, _ = load_transport(response=httpx.Response(
        200, json={"ok": True, "result": {
            "message_id": 432, "chat": {"id": 999},
        }},
    ))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_telegram_429_is_unknown_not_safe_to_retry():
    _, adapter, _, _ = load_transport(response=httpx.Response(429))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_telegram_403_is_explicitly_rejected():
    _, adapter, _, _ = load_transport(response=httpx.Response(403))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.FAILED


@pytest.mark.asyncio
async def test_timeout_is_not_converted_into_fake_sent_receipt():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.side_effect = httpx.TimeoutException("network uncertain")
    with pytest.raises(httpx.TimeoutException):
        await adapter.send(connection=connection(), delivery=delivery())


@pytest.mark.asyncio
async def test_generic_plugin_hook_cannot_act_as_ai_or_delivery_path():
    _, adapter, _, client = load_transport()
    with pytest.raises(PermissionError, match="no generic hook"):
        await adapter.execute_hook(None, None)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [0, -1, True, "432", None])
async def test_invalid_telegram_message_id_never_proves_sent(message_id):
    _, adapter, _, client = load_transport(response=httpx.Response(
        200, json={"ok": True, "result": {
            "message_id": message_id, "chat": {"id": 901},
        }},
    ))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
    client.post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"ok": False, "result": {"message_id": 432, "chat": {"id": 901}}},
    {"ok": True, "result": {"message_id": 432, "chat": {"id": "901"}}},
    {"ok": True, "result": {"message_id": 432, "chat": {"id": True}}},
])
async def test_inconsistent_telegram_success_body_is_unknown(body):
    _, adapter, _, client = load_transport(response=httpx.Response(200, json=body))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
    client.post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    (200, ChannelDeliveryState.SENT),
    (429, ChannelDeliveryState.UNKNOWN),
])
async def test_real_telegram_adapter_receipt_flows_through_canonical_delivery_service(
    monkeypatch, status, expected,
):
    """Transport-to-delivery integration: provider evidence becomes SQL receipt.

    Runs without a Telegram account, but uses the real installed adapter, its
    host-bound network dependency, policy gates, and delivery service.
    """
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.persistence.repositories.channel_repository import (
        ClaimedChannelDelivery, ChannelDeliveryPreflight,
    )
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService

    response = (
        httpx.Response(200, json={"ok": True, "result": {
            "message_id": 432, "chat": {"id": 901},
        }})
        if status == 200 else httpx.Response(status)
    )
    kernel, adapter, _, client = load_transport(response=response)
    # This unit integration supplies the host-validated installation snapshot.
    # The separate PluginKernel lifecycle contracts prove the real registration
    # gate; loading an adapter alone does not activate that registry.
    manifest = kernel.loader.load_manifest("telegram-bot")
    monkeypatch.setattr(
        kernel, "get_channel_activation_manifest",
        lambda plugin_id: manifest if plugin_id == "telegram-bot" else None,
    )
    monkeypatch.setattr(
        kernel, "is_canonical_channel_adapter",
        lambda plugin_id, value: plugin_id == "telegram-bot" and value is adapter,
    )
    await adapter.start(connection=connection())
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    outbox = delivery()
    claim = ClaimedChannelDelivery(
        connection=connection(), delivery=outbox, user_id=user,
        external_conversation_id="901",
        claim_token="cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    repo = SimpleNamespace(
        get_delivery_preflight=AsyncMock(return_value=ChannelDeliveryPreflight(
            connection_id=connection().connection_id,
            user_id=user, external_conversation_id="901",
        )),
        get_enabled_connection=AsyncMock(return_value=connection()),
        claim_outbound=AsyncMock(return_value=claim),
        renew_outbound_claim=AsyncMock(return_value=True),
        finalize_outbound_claim=AsyncMock(return_value=True),
    )

    async def with_heartbeat(operation, *, renew, **kwargs):
        assert await renew()
        return await operation

    monkeypatch.setattr(
        "ai_karen_engine.services.channels.delivery.run_with_claim_heartbeat",
        with_heartbeat,
    )
    service = ChannelDeliveryService(kernel=kernel, repository=repo)
    session = service._session_id(
        tenant_id=TENANT, user_id=user,
        connection_id=connection().connection_id,
        external_conversation_id="901",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="telegram-dispatch-proof",
        policy_decision_id="trusted-runtime-decision",
        authorized_user_id=user, authorized_tenant_id=TENANT,
        authorized_session_id=session,
        allowed_plugins=["telegram-bot"],
        allowed_capabilities=["channel.send"],
    )
    sent = await service.dispatch(
        tenant_id=TENANT, delivery_id=outbox.delivery_id,
        adapter=adapter, authorized_plan=plan,
    )
    assert sent is (expected is ChannelDeliveryState.SENT)
    client.post.assert_awaited_once()
    repo.claim_outbound.assert_awaited_once()
    repo.finalize_outbound_claim.assert_awaited_once()
    recorded = repo.finalize_outbound_claim.await_args.kwargs["receipt"]
    assert recorded.state is expected
    assert recorded.provider_message_id == ("432" if status == 200 else None)
    if expected is ChannelDeliveryState.UNKNOWN:
        assert recorded.error_code == "telegram_response_uncertain"
