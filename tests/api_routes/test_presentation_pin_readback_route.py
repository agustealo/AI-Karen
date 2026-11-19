"""KUI-002D3A: authenticated read-only pin ingress never exposes raw rows."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    AdmittedPresentationPin,
    PresentationPinReference,
)
from ai_karen_engine.core.runtime.presentation_pin_readback import (
    PresentationPinReadback,
    ReauthorizedPresentationPin,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE = "22222222-2222-5222-8222-222222222222"
PIN = "88888888-8888-4888-8888-888888888888"


def enable(monkeypatch, *, bridge=True, durable=True):
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=bridge, enable_ag_ui_durable_runs=durable
        )),
    )


def principal(monkeypatch, *, denied=None):
    ctx = SimpleNamespace(
        user_id=USER, tenant_id=TENANT,
        request_id="request", correlation_id="correlation",
        require_authenticated_user=Mock(side_effect=denied),
    )
    construction = Mock(return_value=ctx)
    monkeypatch.setattr(ingress, "_execution_context", construction)
    return ctx, construction


def readback(monkeypatch, *, entries=(), failure=None):
    run = AsyncMock()
    if failure is None:
        run.return_value = tuple(entries)
    else:
        run.side_effect = failure
    factory = Mock(return_value=SimpleNamespace(list_authorized=run))
    monkeypatch.setattr(
        PresentationPinReadback, "list_authorized",
        run,
    )
    return run


def admitted():
    return ReauthorizedPresentationPin(
        pin_id=PIN, position=2, revision=5,
        admitted=AdmittedPresentationPin(
            reference=PresentationPinReference(
                conversation_id=THREAD, assistant_message_id=MESSAGE,
                presentation_id="verified-clock", evidence_ref="clock-proof",
            ),
            component_type="time.observation", schema_version=1,
        ),
    )


@pytest.mark.asyncio
async def test_restore_returns_only_attested_projection_and_no_store_payload(monkeypatch):
    enable(monkeypatch)
    ctx, construct = principal(monkeypatch)
    reader = readback(monkeypatch, entries=[admitted()])
    response = await ingress.get_ag_ui_authorized_pins(
        user={"user_id": USER, "tenant_id": TENANT}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = json.loads(response.body)
    assert data["read_only"] is True
    assert data["pins"] == [{
        "pin_id": PIN, "position": 2, "revision": 5,
        "source": {
            "conversation_id": THREAD,
            "assistant_message_id": MESSAGE,
            "presentation_id": "verified-clock",
            "evidence_ref": "clock-proof",
            "component_type": "time.observation",
            "schema_version": 1,
        },
    }]
    assert "metadata" not in str(data)
    assert "private_tool_payload" not in str(data)
    ctx.require_authenticated_user.assert_called_once()
    assert reader.await_args.kwargs["context"] is ctx
    assert construct.call_args.kwargs["request_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bridge,durable", [(False, True), (True, False)])
async def test_feature_disabled_does_not_construct_context_or_access_storage(
    monkeypatch, bridge, durable
):
    enable(monkeypatch, bridge=bridge, durable=durable)
    ctx, construct = principal(monkeypatch)
    reader = readback(monkeypatch, entries=[admitted()])
    with pytest.raises(HTTPException) as caught:
        await ingress.get_ag_ui_authorized_pins(user={"user_id": USER})
    assert caught.value.status_code == 404
    construct.assert_not_called()
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_principal_is_denied_before_db(monkeypatch):
    enable(monkeypatch)
    ctx, _ = principal(monkeypatch, denied=PermissionError("not verified"))
    reader = readback(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        await ingress.get_ag_ui_authorized_pins(user={"user_id": USER})
    assert caught.value.status_code == 401
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_outage_returns_503_never_fake_empty_success(monkeypatch):
    enable(monkeypatch)
    principal(monkeypatch)
    readback(monkeypatch, failure=RuntimeError("database unavailable"))
    with pytest.raises(HTTPException) as caught:
        await ingress.get_ag_ui_authorized_pins(user={"user_id": USER})
    assert caught.value.status_code == 503
    assert caught.value.headers["X-Correlation-Id"]


@pytest.mark.asyncio
async def test_readback_permission_denial_returns_403(monkeypatch):
    enable(monkeypatch)
    principal(monkeypatch)
    readback(monkeypatch, failure=PermissionError("revoked"))
    with pytest.raises(HTTPException) as caught:
        await ingress.get_ag_ui_authorized_pins(user={"user_id": USER})
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_empty_verified_projection_is_explicitly_read_only(monkeypatch):
    enable(monkeypatch)
    principal(monkeypatch)
    readback(monkeypatch)
    response = await ingress.get_ag_ui_authorized_pins(
        user={"user_id": USER, "tenant_id": TENANT}
    )
    assert json.loads(response.body) == {
        "schema_version": 1, "read_only": True, "pins": [],
    }
