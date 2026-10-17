"""Signed native webhook: one host verification, one durable destination, no AI."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_karen_engine.api_routes.channels.webhooks import (
    is_native_channel_webhook_path, router,
)
from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection, InboundChannelEvent, VerifiedIdentityBinding,
)
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
)
from ai_karen_engine.services.channels.ingress import ChannelIngressService

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONNECTION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
NATIVE = f"/api/channels/webhooks/{TENANT}/{CONNECTION}"
TOKEN = "a" * 43


def gateway(*, text="Hello Karen", verified=True, enabled=True, canonical=True):
    conn = ChannelConnection(
        tenant_id=TENANT, connection_id=CONNECTION,
        installation_id="telegram-bot",
        provider_account_id="bot-account",
        credential_handle="vault://reference",
        revision=3, enabled=True,
    )
    event = InboundChannelEvent(
        connection_id=CONNECTION,
        external_event_id="741",
        external_sender_id="901",
        external_conversation_id="901",
        message_kind="text", text=text,
    )
    adapter = SimpleNamespace(
        verify_event=AsyncMock(return_value=verified),
        normalize_event=AsyncMock(return_value=event),
    )
    repo = SimpleNamespace(
        get_enabled_connection=AsyncMock(return_value=conn if enabled else None),
        consume_verified_link=AsyncMock(return_value=VerifiedIdentityBinding(
            tenant_id=TENANT, user_id=USER, connection_id=CONNECTION,
            external_sender_id="901",
            binding_id="dddddddd-dddd-dddd-dddd-dddddddddddd", revision=1,
        )),
        admit_verified_inbound=AsyncMock(return_value=SimpleNamespace(
            tenant_id=TENANT, user_id=USER, inbox_id="inbox-1",
            correlation_id="correlation-1", inserted=True,
        )),
    )
    kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda name: (
            SimpleNamespace(
                capabilities=SimpleNamespace(
                    communication_channel=SimpleNamespace(inbound={"text"})
                )
            ) if name == "telegram-bot" else None
        ),
        loader=SimpleNamespace(load_extension=lambda name: adapter),
        is_canonical_channel_adapter=lambda name, value: canonical and value is adapter,
    )
    ingress = ChannelIngressService(
        kernel=kernel, repository=repo, max_native_body_bytes=65_536,
    )
    return ingress, repo, adapter


@pytest.mark.asyncio
async def test_plain_event_admitted_once_from_installed_adapter():
    ingress, repo, adapter = gateway()
    result = await ingress.verify_and_route_installed(
        tenant_id=TENANT, connection_id=CONNECTION,
        headers={"X-Telegram-Bot-Api-Secret-Token": "native-secret"},
        body=b"native-data",
    )
    assert result == "admitted"
    adapter.verify_event.assert_awaited_once()
    adapter.normalize_event.assert_awaited_once()
    repo.admit_verified_inbound.assert_awaited_once()
    repo.consume_verified_link.assert_not_awaited()
    assert repo.get_enabled_connection.await_count == 2


@pytest.mark.asyncio
async def test_link_event_consumed_without_chat_or_second_native_verification():
    ingress, repo, adapter = gateway(text="/link " + TOKEN)
    result = await ingress.verify_and_route_installed(
        tenant_id=TENANT, connection_id=CONNECTION,
        headers={"X-Telegram-Bot-Api-Secret-Token": "native-secret"},
        body=b"native-data",
    )
    assert result == "linked"
    adapter.verify_event.assert_awaited_once()
    adapter.normalize_event.assert_awaited_once()
    repo.admit_verified_inbound.assert_not_awaited()
    args = repo.consume_verified_link.await_args.kwargs
    assert args["external_sender_id"] == "901"
    assert args["proof_digest"] == hashlib.sha256(TOKEN.encode("ascii")).hexdigest()
    assert "user_id" not in args
    assert TOKEN not in str(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "/link", "/link bad",
    "/link " + TOKEN + " extra",
    "/link " + TOKEN + "\nwith trailing text",
    " /link " + TOKEN,
    "\t/link " + TOKEN,
    "/LINK " + TOKEN,
    "/link@KarenTelegramBot " + TOKEN,
    " /Link@Karen_Telegram_Bot " + TOKEN,
])
async def test_malformed_or_replayed_link_prefix_is_never_a_chat_message(text):
    ingress, repo, _ = gateway(text=text)
    with pytest.raises(ChannelAdmissionDenied):
        await ingress.verify_and_route_installed(
            tenant_id=TENANT, connection_id=CONNECTION,
            headers={}, body=b"native-data",
        )
    repo.admit_verified_inbound.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("verified,enabled,canonical", [
    (False, True, True),
    (True, False, True),
    (True, True, False),
])
async def test_invalid_native_context_never_reaches_any_persistence(
    verified, enabled, canonical,
):
    ingress, repo, _ = gateway(
        verified=verified, enabled=enabled, canonical=canonical,
    )
    with pytest.raises(ChannelAdmissionDenied):
        await ingress.verify_and_route_installed(
            tenant_id=TENANT, connection_id=CONNECTION,
            headers={}, body=b"native-data",
        )
    repo.admit_verified_inbound.assert_not_awaited()
    repo.consume_verified_link.assert_not_awaited()


def isolated_app(ingress=None):
    app = FastAPI()
    app.include_router(router)
    if ingress is not None:
        app.state.channel_ingress_service = ingress
    return app


def test_native_webhook_path_exemption_is_strict():
    assert is_native_channel_webhook_path(NATIVE, "POST")
    for path, method in [
        (NATIVE, "GET"),
        (NATIVE + "/", "POST"),
        ("/api/channels/webhooks/" + TENANT + "/arbitrary", "POST"),
        ("/api/channels/webhooks/" + TENANT + "/" + CONNECTION + "/execute", "POST"),
        ("/api/channels/webhooks/invalid/" + CONNECTION, "POST"),
        ("/api/other/" + TENANT + "/" + CONNECTION, "POST"),
    ]:
        assert is_native_channel_webhook_path(path, method) is False


def test_public_webhook_is_unavailable_without_explicit_host_binding():
    with TestClient(isolated_app()) as client:
        response = client.post(NATIVE, content=b"native-data")
    assert response.status_code == 503
    assert response.json() == {"detail": "Channel ingress unavailable"}


def test_webhook_ack_only_after_durable_admission():
    ingress, _, _ = gateway()
    with TestClient(isolated_app(ingress)) as client:
        response = client.post(
            NATIVE, content=b"native-data",
            headers={"X-Telegram-Bot-Api-Secret-Token": "native-secret"},
        )
    assert response.status_code == 202
    assert response.json() == {"accepted": True}


def test_webhook_rejects_oversized_payload_before_adapter():
    ingress, repo, adapter = gateway()
    with TestClient(isolated_app(ingress)) as client:
        response = client.post(NATIVE, content=b"a" * (ingress.max_native_body_bytes + 1))
    assert response.status_code == 413
    adapter.verify_event.assert_not_awaited()
    repo.admit_verified_inbound.assert_not_awaited()


def test_webhook_denies_native_signature_failure_without_leaking_data():
    ingress, repo, _ = gateway(verified=False)
    with TestClient(isolated_app(ingress)) as client:
        response = client.post(NATIVE, content=b"secret-body-contents")
    assert response.status_code == 403
    assert "secret-body" not in response.text
    assert "telegram" not in response.text
    repo.admit_verified_inbound.assert_not_awaited()


def test_webhook_does_not_claim_success_if_database_is_unavailable():
    ingress, repo, _ = gateway()
    repo.admit_verified_inbound.side_effect = OSError("private database location")
    with TestClient(isolated_app(ingress)) as client:
        response = client.post(NATIVE, content=b"native-data")
    assert response.status_code == 503
    assert "private database" not in response.text


def test_global_auth_allows_only_exact_native_post_without_session(monkeypatch):
    from ai_karen_engine.server import routers as canonical_routers
    from ai_karen_engine.auth.auth_middleware import AuthenticationError

    ingress, repo, _ = gateway()
    authentication = AsyncMock(side_effect=AuthenticationError("No valid JWT"))
    fake_auth = SimpleNamespace(
        is_public_endpoint=lambda path: False,
        authenticate_request=authentication,
    )
    monkeypatch.setattr(canonical_routers, "get_auth_middleware", lambda: fake_auth)
    monkeypatch.setattr(
        canonical_routers.auth_config, "should_bypass_auth", lambda: False,
    )
    app = isolated_app(ingress)
    app.add_api_route(
        "/api/channel-admin/private-test", lambda: {"unsafe": True},
        methods=["GET"],
    )
    canonical_routers.configure_authentication_middleware(app)

    with TestClient(app) as client:
        signed = client.post(
            NATIVE, content=b"native-data",
            headers={"X-Telegram-Bot-Api-Secret-Token": "native-secret"},
        )
        assert signed.status_code == 202
        authentication.assert_not_awaited()
        unsigned_admin = client.get("/api/channel-admin/private-test")
        assert unsigned_admin.status_code == 401
    authentication.assert_awaited_once()
    repo.admit_verified_inbound.assert_awaited_once()
