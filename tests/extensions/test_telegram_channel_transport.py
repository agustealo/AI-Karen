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
    client = SimpleNamespace(
        get=AsyncMock(return_value=httpx.Response(200, json={
            "ok": True, "result": {"id": 123456, "is_bot": True},
        })),
        post=AsyncMock(return_value=(
            response if response is not None else httpx.Response(200, json={
                "ok": True,
                "result": {"message_id": 432, "chat": {"id": 901}},
            })
        )),
    )
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


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 301, 302, 307, 308])
async def test_non_200_telegram_response_cannot_fabricate_sent(status):
    _, adapter, _, client = load_transport(response=httpx.Response(
        status, json={"ok": True, "result": {
            "message_id": 432, "chat": {"id": 901},
        }},
    ))
    await adapter.start(connection=connection())
    receipt = await adapter.send(connection=connection(), delivery=delivery())
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_boolean_chat_id_cannot_impersonate_integer_recipient():
    _, adapter, _, client = load_transport(response=httpx.Response(
        200, json={"ok": True, "result": {
            "message_id": 432, "chat": {"id": True},
        }},
    ))
    await adapter.start(connection=connection())
    outgoing = delivery().model_copy(update={"destination_id": "1"})
    receipt = await adapter.send(connection=connection(), delivery=outgoing)
    assert receipt.state is ChannelDeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_activation_requires_verified_telegram_bot_identity():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.assert_awaited_once()
    assert client.get.await_args.args[0].endswith("/getMe")
    status = await adapter.health(connection=connection())
    assert status["running"] is True
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", [
    httpx.Response(401, json={"ok": False}),
    httpx.Response(429),
    httpx.Response(200, json={"ok": False, "result": {"id": 10, "is_bot": True}}),
    httpx.Response(200, json={"ok": True, "result": {"id": True, "is_bot": True}}),
    httpx.Response(200, json={"ok": True, "result": {"id": 0, "is_bot": True}}),
    httpx.Response(200, json={"ok": True, "result": {"id": 10, "is_bot": False}}),
    httpx.Response(200, json={"ok": True, "result": []}),
    httpx.Response(200, content=b"not-json"),
])
async def test_telegram_activation_fails_closed_on_unverified_bot(probe):
    _, adapter, _, client = load_transport()
    client.get.return_value = probe
    with pytest.raises(PermissionError, match="identity check failed"):
        await adapter.start(connection=connection())
    assert (await adapter.health(connection=connection()))["running"] is False
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_probe_network_failure_does_not_expose_token_or_activate():
    _, adapter, _, client = load_transport()
    client.get.side_effect = httpx.TimeoutException("upstream secret in exception")
    with pytest.raises(PermissionError) as caught:
        await adapter.start(connection=connection())
    assert TOKEN not in str(caught.value)
    assert "upstream secret" not in str(caught.value)
    assert (await adapter.health(connection=connection()))["running"] is False
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_webhook_inspection_projects_only_redacted_provider_evidence():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True,
        "result": {
            "url": (
                "https://karen.example/api/channels/webhooks/"
                f"{TENANT}/telegram-conn-1"
            ),
            "pending_update_count": 3,
            "last_error_date": 1730000000,
            "last_error_message": "private provider diagnostic",
            "ip_address": "203.0.113.10",
        },
    })
    evidence = await adapter.inspect_webhook(connection=connection())
    assert evidence == {
        "registered": True,
        "path_matches": True,
        "pending_update_count": 3,
        "provider_reported_error": True,
        "endpoint_origin_verified": False,
    }
    assert TOKEN not in str(evidence)
    assert "karen.example" not in str(evidence)
    assert "private provider diagnostic" not in str(evidence)
    assert "203.0.113.10" not in str(evidence)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_webhook_not_registered_is_not_reported_ready():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": {"url": "", "pending_update_count": 0},
    })
    evidence = await adapter.inspect_webhook(connection=connection())
    assert evidence["registered"] is False
    assert evidence["path_matches"] is False
    assert evidence["endpoint_origin_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_info", [
    {"url": "http://karen.example/api/channels/webhooks/other", "pending_update_count": 0},
    {"url": "https://guest:pass@karen.example/hook", "pending_update_count": 0},
    {"url": "https://karen.example/hook?bot_token=abc", "pending_update_count": 0},
    {"url": "https://karen.example/hook#fragment", "pending_update_count": 0},
    {"url": "https://karen.example/hook", "pending_update_count": True},
    {"url": "https://karen.example/hook", "pending_update_count": -1},
    {"url": "https://karen.example/hook", "pending_update_count": 1000001},
    {"url": "https://karen.example/hook", "pending_update_count": 0, "last_error_date": "yesterday"},
])
async def test_invalid_telegram_webhook_info_fails_closed(provider_info):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": provider_info,
    })
    with pytest.raises(PermissionError, match="inspection unavailable"):
        await adapter.inspect_webhook(connection=connection())
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_webhook_mismatched_route_is_not_connection_proof():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True,
        "result": {"url": "https://karen.example/foreign-hook", "pending_update_count": 0},
    })
    evidence = await adapter.inspect_webhook(connection=connection())
    assert evidence["registered"] is True
    assert evidence["path_matches"] is False
    assert evidence["endpoint_origin_verified"] is False


@pytest.mark.asyncio
async def test_webhook_probe_requires_host_activation_and_masks_network_errors():
    _, adapter, _, client = load_transport()
    with pytest.raises(PermissionError, match="not active"):
        await adapter.inspect_webhook(connection=connection())
    client.get.assert_not_awaited()
    await adapter.start(connection=connection())
    client.get.side_effect = httpx.TimeoutException(f"secret {TOKEN}")
    with pytest.raises(PermissionError) as error:
        await adapter.inspect_webhook(connection=connection())
    assert TOKEN not in str(error.value)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_telegram_registration_submits_secret_and_verifies_exact_url():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    destination = (
        f"https://hooks.example.org/api/channels/webhooks/"
        f"{TENANT}/telegram-conn-1"
    )
    client.post.return_value = httpx.Response(200, json={
        "ok": True, "result": True,
    })
    client.get.side_effect = [
        httpx.Response(200, json={
            "ok": True, "result": {"id": 123456, "is_bot": True},
        }),
        httpx.Response(200, json={
            "ok": True, "result": {"url": destination, "pending_update_count": 0},
        }),
    ]
    result = await adapter.register_webhook(
        connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=123456,
    )
    assert result == {
        "provider_registration_verified": True, "live_connected": False,
    }
    assert client.post.await_args.kwargs["json"] == {
        "url": destination,
        "secret_token": SECRET,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    }
    assert client.post.await_args.args[0].endswith("/setWebhook")
    assert client.get.await_args.args[0].endswith("/getWebhookInfo")
    assert SECRET not in str(result)
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [
    "http://hooks.example.org", "https://hooks.example.org/path",
    "https://hooks.example.org:8443", "https://user:pass@hooks.example.org",
    "https://hooks.example.org?key=one", "https://hooks.example.org/",
    "",
])
async def test_telegram_registration_invalid_origin_never_mutates_provider(origin):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.reset_mock()
    with pytest.raises(PermissionError, match="registration unavailable"):
        await adapter.register_webhook(
            connection=connection(), public_origin=origin,
            expected_bot_id=123456,
        )
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_response", [
    httpx.Response(401, json={"ok": False}),
    httpx.Response(200, json={"ok": False, "description": "denied"}),
    httpx.Response(200, json={"ok": True, "result": False}),
    httpx.Response(200, json={"ok": True, "result": {"wrong": "type"}}),
])
async def test_telegram_registration_denial_never_reports_provider_success(provider_response):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.return_value = provider_response
    client.get.reset_mock()
    with pytest.raises(PermissionError, match="unverified"):
        await adapter.register_webhook(
            connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=123456,
        )
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_registration_unknown_after_provider_post_does_not_fake_rollback():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.return_value = httpx.Response(200, json={"ok": True, "result": True})
    client.get.side_effect = [
        httpx.Response(200, json={
            "ok": True, "result": {"id": 123456, "is_bot": True},
        }),
        httpx.Response(200, json={
            "ok": True, "result": {
                "url": f"https://foreign.example/api/channels/webhooks/{TENANT}/telegram-conn-1",
            },
        }),
    ]
    with pytest.raises(PermissionError, match="unverified"):
        await adapter.register_webhook(
            connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=123456,
        )
    client.post.assert_awaited_once()
    client.get.assert_awaited()


@pytest.mark.asyncio
async def test_telegram_registration_network_uncertainty_masks_bot_token():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.side_effect = httpx.TimeoutException(f"secret {TOKEN}")
    with pytest.raises(PermissionError) as error:
        await adapter.register_webhook(
            connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=123456,
        )
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_telegram_read_only_reconciliation_observes_exact_provider_url():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    target = (
        f"https://hooks.example.org/api/channels/webhooks/"
        f"{TENANT}/telegram-conn-1"
    )
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": {"url": target},
    })
    client.post.reset_mock()
    evidence = await adapter.observe_registration(
        connection=connection(), public_origin="https://hooks.example.org",
    )
    assert evidence == {
        "provider_url_matches": True,
        "provider_webhook_registered": True,
        "live_connected": False,
    }
    client.post.assert_not_awaited()
    assert TOKEN not in str(evidence)


@pytest.mark.asyncio
async def test_telegram_read_only_reconciliation_does_not_accept_foreign_url():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": {
            "url": f"https://foreign.example/api/channels/webhooks/{TENANT}/telegram-conn-1",
        },
    })
    evidence = await adapter.observe_registration(
        connection=connection(), public_origin="https://hooks.example.org",
    )
    assert evidence["provider_webhook_registered"] is True
    assert evidence["provider_url_matches"] is False
    assert evidence["live_connected"] is False


@pytest.mark.asyncio
async def test_telegram_read_only_reconciliation_masks_failed_provider_response():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(500, json={
        "error": "contains bot token",
    })
    with pytest.raises(PermissionError, match="observation unavailable"):
        await adapter.observe_registration(
            connection=connection(), public_origin="https://hooks.example.org",
        )


@pytest.mark.asyncio
async def test_telegram_verified_bot_identity_is_numeric_and_never_a_token():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": {"id": 123456, "is_bot": True},
    })
    bot_id = await adapter.identify_bot(connection=connection())
    assert bot_id == 123456
    assert type(bot_id) is int
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [
    {"id": "123456", "is_bot": True},
    {"id": True, "is_bot": True},
    {"id": 0, "is_bot": True},
    {"id": 2**63, "is_bot": True},
    {"id": 123456, "is_bot": False},
    {"id": 123456},
])
async def test_telegram_global_ownership_refuses_invalid_provider_identity(identity):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": identity,
    })
    with pytest.raises(PermissionError, match="identity verification unavailable"):
        await adapter.identify_bot(connection=connection())


@pytest.mark.asyncio
async def test_telegram_global_ownership_masks_provider_identity_errors():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.side_effect = httpx.TimeoutException(f"private {TOKEN}")
    with pytest.raises(PermissionError) as error:
        await adapter.identify_bot(connection=connection())
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_telegram_registration_refuses_rotated_token_identity_before_remote_post():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.reset_mock()
    client.get.return_value = httpx.Response(200, json={
        "ok": True, "result": {"id": 987654, "is_bot": True},
    })
    with pytest.raises(PermissionError, match="unverified"):
        await adapter.register_webhook(
            connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=123456,
        )
    client.get.assert_awaited()
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bot_id", [0, -1, True, "123456", 2**63])
async def test_telegram_registration_rejects_untrusted_expected_bot_id(bot_id):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.post.reset_mock()
    client.get.reset_mock()
    with pytest.raises(PermissionError, match="ownership verification unavailable"):
        await adapter.register_webhook(
            connection=connection(), public_origin="https://hooks.example.org",
            expected_bot_id=bot_id,
        )
    client.get.assert_not_awaited()
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_recovery_verifies_bot_and_exact_webhook_with_same_token():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    expected = (
        f"https://hooks.example.org/api/channels/webhooks/"
        f"{TENANT}/telegram-conn-1"
    )
    client.get.side_effect = [
        httpx.Response(200, json={
            "ok": True, "result": {"id": 123456, "is_bot": True},
        }),
        httpx.Response(200, json={
            "ok": True, "result": {"url": expected},
        }),
    ]
    client.post.reset_mock()
    assert await adapter.verify_registration_for_recovery(
        connection=connection(), public_origin="https://hooks.example.org",
    ) == 123456
    assert client.get.await_count >= 2
    assert all(
        f"/bot{TOKEN}/" in args.args[0]
        for args in client.get.await_args_list[-2:]
    )
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "", "https://outside.example",
    "https://hooks.example.org/api/channels/webhooks/foreign/connection",
    "https://hooks.example.org/api/channels/webhooks/"
])
async def test_telegram_recovery_rejects_mismatched_webhook_without_mutation(url):
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.side_effect = [
        httpx.Response(200, json={
            "ok": True, "result": {"id": 123456, "is_bot": True},
        }),
        httpx.Response(200, json={
            "ok": True, "result": {"url": url},
        }),
    ]
    client.post.reset_mock()
    with pytest.raises(PermissionError, match="recovery verification unavailable"):
        await adapter.verify_registration_for_recovery(
            connection=connection(), public_origin="https://hooks.example.org",
        )
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_recovery_provider_error_masks_vault_bot_token():
    _, adapter, _, client = load_transport()
    await adapter.start(connection=connection())
    client.get.side_effect = httpx.TimeoutException(f"private {TOKEN}")
    with pytest.raises(PermissionError) as error:
        await adapter.verify_registration_for_recovery(
            connection=connection(), public_origin="https://hooks.example.org",
        )
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_status", "sender", "secret", "expected_http", "expected_state"),
    [
        (200, 901, SECRET, 200, ChannelDeliveryState.SENT),
        (429, 901, SECRET, 200, ChannelDeliveryState.UNKNOWN),
        (200, 901, "invalid-webhook-secret", 403, None),
        (200, 902, SECRET, 403, None),
    ],
)
async def test_telegram_signed_webhook_executes_and_records_real_adapter_send_contract(
    monkeypatch, provider_status, sender, secret, expected_http, expected_state,
):
    """Offline whole-chain contract, not an assertion of a live Telegram account.

    Exercise the actual HTTP route, installed protocol adapter, tenant-bound
    admission, leased worker, canonical ChatRuntime bridge, policy-gated
    dispatcher and the installed adapter's provider response parser together.
    The repository and Telegram HTTP peer are deliberately simulated: the
    separate PostgreSQL tests own RLS/transactional claims, and only an observed
    real-provider round trip can establish live operational readiness.
    """
    import asyncio
    import uuid

    from fastapi import FastAPI

    from ai_karen_engine.api_routes.channels.webhooks import router
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionStatus,
    )
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
    from ai_karen_engine.persistence.repositories.channel_repository import (
        ChannelAdmissionDenied,
        ChannelDeliveryPreflight,
        ClaimedChannelDelivery,
        ClaimedChannelMessage,
        InboundAdmission,
    )
    from ai_karen_engine.services.auth.auth_service import UserStatus
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    from ai_karen_engine.services.channels.execution import ChannelExecutionService
    from ai_karen_engine.services.channels.ingress import ChannelIngressService
    from ai_karen_engine.services.channels.worker import ChannelInboxWorker

    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    inbox_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    binding_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    claim_token = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    conn = connection().model_copy(update={"connection_id": str(uuid.uuid4())})
    response = (
        httpx.Response(200, json={
            "ok": True,
            "result": {"message_id": 432, "chat": {"id": 901}},
        })
        if provider_status == 200 else httpx.Response(provider_status)
    )
    kernel, adapter, resolver, provider_http = load_transport(response=response)
    manifest = kernel.loader.load_manifest("telegram-bot")
    monkeypatch.setattr(
        kernel, "get_channel_activation_manifest",
        lambda installation_id: (
            manifest if installation_id == "telegram-bot" else None
        ),
    )
    monkeypatch.setattr(
        kernel, "is_canonical_channel_adapter",
        lambda installation_id, candidate: (
            installation_id == "telegram-bot" and candidate is adapter
        ),
    )
    await adapter.start(connection=conn)

    state = {}
    repo = SimpleNamespace(
        get_enabled_connection=AsyncMock(return_value=conn),
        get_connection=AsyncMock(return_value=conn),
        renew_inbound_claim=AsyncMock(return_value=True),
        fail_inbound_claim=AsyncMock(return_value=True),
        renew_outbound_claim=AsyncMock(return_value=True),
        finalize_outbound_claim=AsyncMock(return_value=True),
    )

    async def admit_verified(*, connection, event):
        # Emulate the SQL binding gate, never promote Telegram's forged
        # tenant/user JSON into a Karen principal.
        if (
            connection != conn
            or event.external_sender_id != "901"
            or event.external_conversation_id != "901"
        ):
            raise ChannelAdmissionDenied("No active bound sender")
        state["event"] = event
        receipt = InboundAdmission(
            inbox_id=inbox_id,
            correlation_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            tenant_id=TENANT, user_id=user, binding_id=binding_id,
            inserted=True,
        )
        state["admission"] = receipt
        return receipt

    async def claim_inbound(*, tenant_id, inbox_id, lease_seconds):
        assert tenant_id == TENANT and inbox_id == state["admission"].inbox_id
        assert lease_seconds >= 3
        return claim_token, state["admission"]

    async def load_claimed(*, tenant_id, inbox_id, claim_token):
        assert tenant_id == TENANT and inbox_id == state["admission"].inbox_id
        assert claim_token == "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        event = state["event"]
        return ClaimedChannelMessage(
            inbox_id=inbox_id, correlation_id=state["admission"].correlation_id,
            tenant_id=TENANT, user_id=user, binding_id=binding_id,
            connection_id=conn.connection_id,
            external_conversation_id=event.external_conversation_id,
            external_sender_id=event.external_sender_id,
            message_kind=event.message_kind, text=event.text,
        )

    async def stage_delivery(*, tenant_id, inbox_id, claim_token, delivery):
        assert tenant_id == TENANT and inbox_id == state["admission"].inbox_id
        assert claim_token == "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        state["delivery"] = delivery
        return True

    async def get_preflight(*, tenant_id, delivery_id):
        if tenant_id != TENANT or state.get("delivery") is None:
            return None
        if state["delivery"].delivery_id != delivery_id:
            return None
        return ChannelDeliveryPreflight(
            connection_id=conn.connection_id,
            user_id=user, external_conversation_id="901",
        )

    async def claim_outbound(*, tenant_id, delivery_id, lease_seconds):
        assert tenant_id == TENANT and lease_seconds >= 3
        assert delivery_id == state["delivery"].delivery_id
        return ClaimedChannelDelivery(
            connection=conn, delivery=state["delivery"],
            user_id=user, external_conversation_id="901",
            claim_token="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )

    repo.admit_verified_inbound = AsyncMock(side_effect=admit_verified)
    repo.claim_inbound = AsyncMock(side_effect=claim_inbound)
    repo.load_claimed_message = AsyncMock(side_effect=load_claimed)
    repo.complete_and_stage_delivery = AsyncMock(side_effect=stage_delivery)
    repo.get_delivery_preflight = AsyncMock(side_effect=get_preflight)
    repo.claim_outbound = AsyncMock(side_effect=claim_outbound)

    chat_runtime = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        answer="Hello from ChatRuntime",
        status=ChatExecutionStatus.OK,
        metadata=SimpleNamespace(to_dict=lambda: {
            "response_source": "model", "degraded_mode": False,
        }),
    )))
    principal_lookup = AsyncMock(return_value=SimpleNamespace(
        id=user, tenant_id=TENANT, status=UserStatus.ACTIVE, roles=["user"],
    ))
    execution = ChannelExecutionService(
        repository=repo, chat_runtime=chat_runtime,
        principal_lookup=principal_lookup,
    )
    delivery_service = ChannelDeliveryService(kernel=kernel, repository=repo)
    policy_issues = []

    async def dispatch_authorized(*, tenant_id, delivery_id, user_id, session_id):
        policy_issues.append((tenant_id, delivery_id, user_id, session_id))
        plan = AuthorizedExecutionPlan(
            execution_id="telegram-roundtrip-contract",
            policy_decision_id="runtime-policy-accepted",
            authorized_tenant_id=tenant_id,
            authorized_user_id=user_id,
            authorized_session_id=session_id,
            allowed_plugins=["telegram-bot"],
            allowed_capabilities=["channel.send"],
        )
        return await delivery_service.dispatch(
            tenant_id=tenant_id, delivery_id=delivery_id,
            adapter=adapter, authorized_plan=plan,
        )

    async def with_heartbeat(operation, *, renew, **kwargs):
        assert await renew() is True
        return await operation

    monkeypatch.setattr(
        "ai_karen_engine.services.channels.execution.run_with_claim_heartbeat",
        with_heartbeat,
    )
    monkeypatch.setattr(
        "ai_karen_engine.services.channels.delivery.run_with_claim_heartbeat",
        with_heartbeat,
    )
    worker = ChannelInboxWorker(
        repository=repo, execution=execution, max_inflight=1,
        dispatch_outbox=dispatch_authorized,
    )
    worker.start()
    ingress = ChannelIngressService(
        kernel=kernel, repository=repo, max_native_body_bytes=65_536,
        on_admitted=worker.submit,
    )
    app = FastAPI()
    app.include_router(router)
    app.state.channel_ingress_service = ingress

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://telegram-contract.test",
        ) as client:
            accepted = await client.post(
                f"/api/channels/webhooks/{TENANT}/{conn.connection_id}",
                content=native_message(sender=sender, chat=sender),
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            )
        assert accepted.status_code == expected_http
        if expected_state is None:
            assert accepted.json()["detail"] == "Native channel event rejected"
            repo.admit_verified_inbound.assert_not_awaited() if secret != SECRET else (
                repo.admit_verified_inbound.assert_awaited_once()
            )
            repo.claim_inbound.assert_not_awaited()
            chat_runtime.execute.assert_not_awaited()
            provider_http.post.assert_not_awaited()
            repo.finalize_outbound_claim.assert_not_awaited()
            return

        assert accepted.json() == {"accepted": True}
        await asyncio.gather(*tuple(worker._tasks))
        repo.admit_verified_inbound.assert_awaited_once()
        repo.claim_inbound.assert_awaited_once()
        principal_lookup.assert_awaited_once_with(tenant_id=TENANT, user_id=user)
        chat_runtime.execute.assert_awaited_once()
        runtime_request = chat_runtime.execute.await_args.args[0]
        assert runtime_request.context.user_id == user
        assert runtime_request.context.tenant_id == TENANT
        assert runtime_request.context.request_id == inbox_id
        assert runtime_request.messages == [
            {"role": "user", "content": "Hello Karen"},
        ]
        staged = state["delivery"]
        assert staged.text == "Hello from ChatRuntime"
        assert staged.destination_id == "901"
        assert staged.idempotency_key == inbox_id
        assert policy_issues == [(
            TENANT, staged.delivery_id, user,
            ChannelDeliveryService._session_id(
                tenant_id=TENANT, user_id=user,
                connection_id=conn.connection_id,
                external_conversation_id="901",
            ),
        )]
        provider_http.post.assert_awaited_once()
        assert provider_http.post.await_args.kwargs["json"] == {
            "chat_id": 901, "text": "Hello from ChatRuntime",
        }
        repo.finalize_outbound_claim.assert_awaited_once()
        recorded = repo.finalize_outbound_claim.await_args.kwargs["receipt"]
        assert recorded.state is expected_state
        assert recorded.delivery_id == staged.delivery_id
        if expected_state is ChannelDeliveryState.SENT:
            assert recorded.provider_message_id == "432"
            assert recorded.provider_receipt_id is None
        else:
            assert recorded.provider_message_id is None
            assert recorded.error_code == "telegram_response_uncertain"
        assert resolver.await_count > 0
    finally:
        await worker.shutdown()
        await adapter.stop(connection=conn)
