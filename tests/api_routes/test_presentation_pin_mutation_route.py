"""KUI-002D3B2B: opt-in authenticated presentation-pin HTTP mutation boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.core.runtime.presentation_pin_mutation import PresentationPinMutation
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    PresentationPinConflict,
    PresentationPinUnavailable,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE = "22222222-2222-5222-8222-222222222222"
PIN = "88888888-8888-4888-8888-888888888888"
KEY = "55555555-5555-4555-8555-555555555555"
RECEIPT = "99999999-9999-4999-8999-999999999999"


def enable(monkeypatch, *, bridge=True, durable=True, writes=True):
    monkeypatch.setattr(
        ingress, "get_runtime_settings",
        lambda: SimpleNamespace(
            features=SimpleNamespace(
                enable_ag_ui_bridge=bridge,
                enable_ag_ui_durable_runs=durable,
                enable_presentation_pin_mutations=writes,
            )
        ),
    )


def principal(monkeypatch, *, denied=None):
    ctx = SimpleNamespace(
        user_id=USER,
        tenant_id=TENANT,
        request_id="server-request",
        correlation_id="server-correlation",
        require_authenticated_user=Mock(side_effect=denied),
    )
    factory = Mock(return_value=ctx)
    monkeypatch.setattr(ingress, "_execution_context", factory)
    return ctx, factory


def runtime(monkeypatch, *, failure=None):
    run = AsyncMock()
    if failure is not None:
        run.side_effect = failure
    else:
        run.return_value = SimpleNamespace(
            receipt_id=RECEIPT,
            idempotency_key=KEY,
            request_id="first-committed-request",
            correlation_id="first-committed-correlation",
            operation="unpin",
            outcome="unpinned",
            pin_id=PIN,
            expected_revision=None,
            committed_revision=None,
        )
    monkeypatch.setattr(PresentationPinMutation, "execute", run)
    return run


def request(*, operation="unpin", source=None, pin_id=PIN, revision=None, position=None):
    return ingress.PresentationPinMutationRequest(
        operation=operation,
        idempotency_key=KEY,
        source=source,
        pin_id=pin_id,
        expected_revision=revision,
        position=position,
    )


@pytest.mark.asyncio
async def test_receipt_response_is_authoritative_and_no_store(monkeypatch):
    enable(monkeypatch)
    ctx, factory = principal(monkeypatch)
    execute = runtime(monkeypatch)
    response = await ingress.mutate_ag_ui_authorized_pin(
        request(), user={"user_id": USER, "tenant_id": TENANT}
    )
    result = json.loads(response.body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-correlation-id"]
    assert result == {
        "schema_version": 1,
        "committed": True,
        "receipt": {
            "receipt_id": RECEIPT,
            "idempotency_key": KEY,
            "request_id": "first-committed-request",
            "correlation_id": "first-committed-correlation",
            "operation": "unpin",
            "outcome": "unpinned",
            "pin_id": PIN,
            "expected_revision": None,
            "committed_revision": None,
        },
    }
    assert execute.await_args.kwargs["context"] is ctx
    assert execute.await_args.kwargs["idempotency_key"] == KEY
    assert execute.await_args.kwargs["operation"] == "unpin"
    assert "tenant_id" not in result
    assert "user_id" not in result
    assert factory.call_args.kwargs["request_id"]
    assert factory.call_args.kwargs["correlation_id"]
    ctx.require_authenticated_user.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bridge,durable,writes",
    [(False, True, True), (True, False, True), (True, True, False)],
)
async def test_disabled_flag_denies_before_identity_or_execution(
    monkeypatch, bridge, durable, writes
):
    enable(monkeypatch, bridge=bridge, durable=durable, writes=writes)
    _, factory = principal(monkeypatch)
    execute = runtime(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        await ingress.mutate_ag_ui_authorized_pin(request(), user={})
    assert caught.value.status_code == 404
    factory.assert_not_called()
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_principal_never_calls_runtime(monkeypatch):
    enable(monkeypatch)
    principal(monkeypatch, denied=PermissionError("revoked"))
    execute = runtime(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        await ingress.mutate_ag_ui_authorized_pin(request(), user={})
    assert caught.value.status_code == 401
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_pin_forwards_untrusted_reference_to_runtime_admission(monkeypatch):
    enable(monkeypatch)
    principal(monkeypatch)
    execute = runtime(monkeypatch)
    source = ingress.PresentationPinMutationSourceRequest(
        conversation_id=THREAD,
        assistant_message_id=MESSAGE,
        presentation_id="card-verified",
        evidence_ref="evidence-verified",
    )
    await ingress.mutate_ag_ui_authorized_pin(
        request(operation="pin", source=source, pin_id=None, position=0),
        user={"user_id": USER, "tenant_id": TENANT},
    )
    forwarded = execute.await_args.kwargs
    assert forwarded["operation"] == "pin"
    assert forwarded["reference"].conversation_id == THREAD
    assert forwarded["reference"].assistant_message_id == MESSAGE
    assert forwarded["reference"].presentation_id == "card-verified"
    assert forwarded["reference"].evidence_ref == "evidence-verified"
    assert forwarded["pin_id"] is None
    assert forwarded["position"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,status",
    [
        (PresentationPinConflict("duplicate key"), 409),
        (PresentationPinUnavailable("database failed"), 503),
        (PermissionError("revoked"), 403),
        (ValueError("bad input"), 422),
        (RuntimeError("unexpected"), 503),
    ],
)
async def test_conflict_denial_and_outage_never_fake_committed_receipt(
    monkeypatch, failure, status
):
    enable(monkeypatch)
    principal(monkeypatch)
    runtime(monkeypatch, failure=failure)
    with pytest.raises(HTTPException) as caught:
        await ingress.mutate_ag_ui_authorized_pin(
            request(), user={"user_id": USER, "tenant_id": TENANT}
        )
    assert caught.value.status_code == status
    assert "committed" not in str(caught.value.detail)
    assert "database failed" not in str(caught.value.detail)
    assert "unexpected" not in str(caught.value.detail)
    if status == 503:
        assert caught.value.headers["X-Correlation-Id"]


def test_transport_validates_canonical_shape_limits():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        request(position=100)
    with pytest.raises(ValidationError):
        request(revision=0)
    with pytest.raises(ValidationError):
        ingress.PresentationPinMutationRequest(
            operation="execute_plugin", idempotency_key=KEY
        )


def test_operation_shapes_reject_cross_operation_fields_before_replay():
    from pydantic import ValidationError

    source = ingress.PresentationPinMutationSourceRequest(
        conversation_id=THREAD,
        assistant_message_id=MESSAGE,
        presentation_id="card-verified",
        evidence_ref="evidence-verified",
    )
    invalid = [
        {"operation": "pin", "source": source, "pin_id": PIN},
        {"operation": "pin", "source": source, "expected_revision": 1},
        {"operation": "pin", "source": None},
        {"operation": "unpin", "pin_id": PIN, "source": source},
        {"operation": "unpin", "pin_id": PIN, "position": 0},
        {"operation": "unpin", "pin_id": PIN, "expected_revision": 1},
        {"operation": "unpin", "pin_id": None},
        {"operation": "reorder", "pin_id": PIN, "position": 0},
        {"operation": "reorder", "pin_id": PIN, "expected_revision": 1},
        {"operation": "reorder", "pin_id": PIN, "expected_revision": 1, "position": 0, "source": source},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            ingress.PresentationPinMutationRequest(idempotency_key=KEY, **payload)

    valid = ingress.PresentationPinMutationRequest(
        idempotency_key=KEY,
        operation="reorder",
        pin_id=PIN,
        expected_revision=2,
        position=0,
    )
    assert valid.operation == "reorder"
    assert valid.expected_revision == 2
