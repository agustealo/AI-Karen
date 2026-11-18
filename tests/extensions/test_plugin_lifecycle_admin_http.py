"""Authenticated plugin admin lifecycle HTTP contract, no optimistic state."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from ai_karen_engine.api_routes.plugins import plugins as routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_plugin_lifecycle_context
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.services.dependencies import (
    bypass_user_context_func, get_plugin_service,
)
from ai_karen_engine.services.approvals import ApprovalScopeError, ApprovalStateError


def _app(monkeypatch: pytest.MonkeyPatch):
    tenant, actor = str(uuid.uuid4()), str(uuid.uuid4())
    principal = UserData(user_id=actor, tenant_id=tenant, roles=["admin"])
    context = ChatExecutionContext(
        user_id=actor, tenant_id=tenant, session_id="validated-bearer-token-id",
        request_id="request-verified", correlation_id="correlation-verified",
        authenticated_user=principal,
    )
    service = SimpleNamespace(
        prepare_lifecycle_approval=AsyncMock(return_value={
            "status": "pending",
            "approval_id": str(uuid.uuid4()),
            "plugin_id": "timezone-clock",
            "action": "enable",
            "execution_performed": False,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }),
        resume_lifecycle_approval=AsyncMock(return_value={
            "status": "verified_committed",
            "installation_id": "timezone-clock",
            "action": "enable",
            "next_revision": 4,
            "verification_source": "plugin_kernel",
        }),
    )
    audits: list[dict] = []
    monkeypatch.setattr(
        routes, "get_audit_logger",
        lambda: SimpleNamespace(log_audit_event=audits.append),
    )
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/plugins")
    app.dependency_overrides[bypass_user_context_func] = lambda: principal
    app.dependency_overrides[get_plugin_lifecycle_context] = lambda: context
    app.dependency_overrides[get_plugin_service] = lambda: service
    return app, context, service, audits


@pytest.mark.asyncio
async def test_request_approval_is_pending_and_never_runs_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, service, audits = _app(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/plugins/timezone-clock/lifecycle/enable/approval",
            json={},
        )
    assert response.status_code == 202
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "pending"
    assert response.json()["execution_performed"] is False
    service.prepare_lifecycle_approval.assert_awaited_once_with(
        context=context, plugin_id="timezone-clock", action="enable",
    )
    service.resume_lifecycle_approval.assert_not_awaited()
    assert [event["metadata"]["outcome"] for event in audits] == [
        "attempt", "pending",
    ]


@pytest.mark.asyncio
async def test_post_approved_executes_only_through_canonical_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, service, audits = _app(monkeypatch)
    approval_id = str(uuid.uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/plugins/timezone-clock/lifecycle/enable/execute",
            json={"approval_id": approval_id},
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "verified_committed"
    assert response.json()["next_revision"] == 4
    service.resume_lifecycle_approval.assert_awaited_once_with(
        context=context, plugin_id="timezone-clock",
        action="enable", approval_id=approval_id,
    )
    service.prepare_lifecycle_approval.assert_not_awaited()
    assert [event["metadata"]["outcome"] for event in audits] == [
        "attempt", "verified_committed",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {},
    {"approval_id": "not-an-id"},
    {"approval_id": str(uuid.uuid4()), "manifest_checksum": "forged"},
    {"approval_id": str(uuid.uuid4()), "session_id": "forged-session"},
    {"approval_id": str(uuid.uuid4()), "approved": True},
])
async def test_api_rejects_forged_scope_and_unrelated_execution_input(
    monkeypatch: pytest.MonkeyPatch, payload: dict,
) -> None:
    app, _, service, _ = _app(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/plugins/timezone-clock/lifecycle/enable/execute",
            json=payload,
        )
    assert response.status_code == 422
    service.resume_lifecycle_approval.assert_not_awaited()
    service.prepare_lifecycle_approval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status_code", [
    (ApprovalStateError("private approval details"), 409),
    (ApprovalScopeError("private cross-session details"), 403),
    (PermissionError("private backend policy details"), 403),
    (RuntimeError("SQL connection secrets"), 503),
])
async def test_no_approval_drift_or_unknown_outcome_is_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
) -> None:
    app, _, service, audits = _app(monkeypatch)
    service.resume_lifecycle_approval.side_effect = error
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/plugins/timezone-clock/lifecycle/disable/execute",
            json={"approval_id": str(uuid.uuid4())},
        )
    assert response.status_code == status_code
    text = json.dumps(response.json())
    assert "private" not in text
    assert "SQL connection secrets" not in text
    assert audits[-1]["metadata"]["outcome"] == "unverified"


@pytest.mark.asyncio
async def test_missing_verified_commit_never_reaches_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, service, audits = _app(monkeypatch)
    service.resume_lifecycle_approval.return_value = {"status": "unknown"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/plugins/timezone-clock/lifecycle/enable/execute",
            json={"approval_id": str(uuid.uuid4())},
        )
    assert response.status_code == 503
    assert audits[-1]["metadata"]["outcome"] == "unverified"


@pytest.mark.asyncio
async def test_legacy_management_route_is_still_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, service, _ = _app(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/plugins/timezone-clock/enable")
    assert response.status_code == 409
    assert "approval required" in response.json()["detail"].lower()
    service.prepare_lifecycle_approval.assert_not_awaited()
    service.resume_lifecycle_approval.assert_not_awaited()
