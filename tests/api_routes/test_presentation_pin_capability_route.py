"""KUI-002D3K: session-authenticated, non-authorizing pin capability projection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.core.runtime.presentation_pin_mutation import PresentationPinMutation


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"


def configure(monkeypatch, *, bridge=True, durable=True, writes=False):
    features = SimpleNamespace(
        enable_ag_ui_bridge=bridge,
        enable_ag_ui_durable_runs=durable,
        enable_presentation_pin_mutations=writes,
    )
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=features),
    )
    return features


def authenticated(monkeypatch, *, denied=None, tenant=TENANT):
    context = SimpleNamespace(
        user_id=USER,
        tenant_id=tenant,
        request_id="server-request",
        correlation_id="server-correlation",
        require_authenticated_user=Mock(side_effect=denied),
    )
    factory = Mock(return_value=context)
    monkeypatch.setattr(ingress, "_execution_context", factory)
    return context, factory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bridge,durable,writes,allowed",
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, True, True, False),
    ],
)
async def test_capability_contract_is_auth_scoped_and_flag_derived(
    monkeypatch, bridge, durable, writes, allowed,
):
    features = configure(
        monkeypatch, bridge=bridge, durable=durable, writes=writes,
    )
    context, factory = authenticated(monkeypatch)
    result = await ingress.get_ag_ui_pin_mutation_capabilities(
        user={"user_id": USER, "tenant_id": TENANT},
    )
    payload = json.loads(result.body)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-correlation-id"]
    assert payload == {
        "schema_version": 1,
        "mutation_enabled": allowed,
        "allowed_operations": ["unpin", "reorder"] if allowed else [],
        "denial_reason": None if allowed else "mutations_disabled",
    }
    assert "tenant_id" not in payload and "user_id" not in payload
    assert PresentationPinMutation.mutations_enabled(features) is allowed
    context.require_authenticated_user.assert_called_once()
    assert factory.call_args.kwargs["request_id"]
    assert factory.call_args.kwargs["correlation_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied,tenant",
    [(PermissionError("revoked"), TENANT), (None, None)],
)
async def test_unverified_or_unscoped_context_never_gets_capability(
    monkeypatch, denied, tenant,
):
    configure(monkeypatch, writes=True)
    authenticated(monkeypatch, denied=denied, tenant=tenant)
    with pytest.raises(HTTPException) as caught:
        await ingress.get_ag_ui_pin_mutation_capabilities(
            user={"user_id": USER, "tenant_id": TENANT},
        )
    assert caught.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Bearer invalid-pin-capability-token"])
async def test_real_http_dependency_rejects_unsigned_sessions(
    monkeypatch, authorization,
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from ai_karen_engine.core.security.auth_config import auth_config

    configure(monkeypatch, writes=True)
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    app = FastAPI()
    app.include_router(ingress.router)
    headers = {"Authorization": authorization} if authorization else {}
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        response = await http.get("/chat/ag-ui/pins/capabilities", headers=headers)
    assert response.status_code == 401


def test_unknown_or_partial_flags_fail_closed():
    assert PresentationPinMutation.mutations_enabled(SimpleNamespace()) is False
    assert PresentationPinMutation.mutations_enabled(SimpleNamespace(
        enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
    )) is False
