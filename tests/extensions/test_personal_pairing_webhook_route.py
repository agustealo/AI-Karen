"""Signed pairing HTTP ingress is isolated, bounded, and disabled by default."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.channels.webhooks import (
    is_personal_pairing_callback_path, router,
)
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
    PairingEvidenceDenied,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONNECTION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PATH = f"/api/channels/personal/callbacks/{TENANT}/{CONNECTION}"


def application(*, host=None):
    app = FastAPI()
    app.include_router(router)
    if host is not None:
        app.state.channel_host_services = host
    return app


def fake_host(*, error=None):
    # No managed provider, vault or real QR is started by this HTTP test.
    host = object.__new__(ChannelHostServices)
    host.admit_signed_personal_pairing_event = AsyncMock(
        side_effect=error, return_value=SimpleNamespace(phase="qr_available"),
    )
    return host


def test_exact_callback_path_is_only_post_and_requires_two_uuids():
    assert is_personal_pairing_callback_path(PATH, "POST")
    for path, method in (
        (PATH, "GET"),
        (PATH + "/", "POST"),
        (PATH + "/pair", "POST"),
        (f"/api/channels/personal/callbacks/{TENANT}/not-a-uuid", "POST"),
        (f"/api/channels/personal/callbacks/not-a-uuid/{CONNECTION}", "POST"),
        (f"/api/channels/personal/{TENANT}/{CONNECTION}/consent", "POST"),
    ):
        assert not is_personal_pairing_callback_path(path, method)


def test_no_provider_binding_returns_503_without_fabricated_success():
    with TestClient(application()) as client:
        result = client.post(PATH, content=b"opaque-event")
    assert result.status_code == 503
    assert "accepted" not in result.text


def test_only_host_admission_may_acknowledge_callback():
    host = fake_host()
    with TestClient(application(host=host)) as client:
        response = client.post(
            PATH, content=b"opaque-signed-event",
            headers={"X-Karen-Pairing-Signature": "sha256=" + "a" * 64},
        )
    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    host.admit_signed_personal_pairing_event.assert_awaited_once()
    call = host.admit_signed_personal_pairing_event.await_args.kwargs
    assert call["tenant_id"] == TENANT
    assert call["connection_id"] == CONNECTION
    assert call["body"] == b"opaque-signed-event"
    assert call["headers"]["x-karen-pairing-signature"] == "sha256=" + "a" * 64


@pytest.mark.parametrize("length", [0, 16_385])
def test_empty_or_large_payload_denied_before_verification(length):
    host = fake_host()
    with TestClient(application(host=host)) as client:
        response = client.post(PATH, content=b"x" * length)
    assert response.status_code in (400, 413)
    host.admit_signed_personal_pairing_event.assert_not_awaited()


def test_invalid_signature_is_rejected_without_leaking_provider_details():
    host = fake_host(error=PairingEvidenceDenied("private vault secret"))
    with TestClient(application(host=host)) as client:
        response = client.post(PATH, content=b"invalid")
    assert response.status_code == 403
    assert "private vault secret" not in response.text


def test_database_failure_does_not_appear_as_accepted_pairing():
    host = fake_host(error=OSError("private database host"))
    with TestClient(application(host=host)) as client:
        response = client.post(PATH, content=b"payload")
    assert response.status_code == 503
    assert "private database host" not in response.text


def test_global_auth_exempts_only_signed_provider_callback(monkeypatch):
    from ai_karen_engine.auth.auth_middleware import AuthenticationError
    from ai_karen_engine.server import routers as canonical_routers

    authentication = AsyncMock(side_effect=AuthenticationError("Invalid JWT"))
    monkeypatch.setattr(
        canonical_routers, "get_auth_middleware",
        lambda: SimpleNamespace(
            is_public_endpoint=lambda path: False,
            authenticate_request=authentication,
        ),
    )
    monkeypatch.setattr(
        canonical_routers.auth_config, "should_bypass_auth", lambda: False,
    )
    host = fake_host()
    app = application(host=host)
    app.add_api_route("/api/channel-admin/private-test",
                      lambda: {"unsafe": True}, methods=["GET"])
    canonical_routers.configure_authentication_middleware(app)
    with TestClient(app) as client:
        callback = client.post(PATH, content=b"signed-data")
        assert callback.status_code == 202
        authentication.assert_not_awaited()
        unsigned = client.get("/api/channel-admin/private-test")
        assert unsigned.status_code == 401
        # A normal user-facing personal-channel route is NOT a public callback.
        user_route = client.post(
            f"/api/channels/personal/{CONNECTION}/provider/consent",
            json={"accepted": True, "policy_version": "v1"},
        )
        assert user_route.status_code in (401, 404)
    assert authentication.await_count == 2
