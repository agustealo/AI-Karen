"""WS-04A9Q: first-party document consent ingress is thin and fail-closed."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from ai_karen_engine.api_routes.automation import approvals as routes
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.services.approvals import (
    ApprovalScopeError,
    ApprovalStateError,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_and_service(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    scope = DocumentConsentApprovalScope(
        tenant_id=str(uuid.uuid4()),
        author_actor_id=str(uuid.uuid4()),
        session_id=uuid.uuid4().hex,
        profile_id=str(uuid.uuid4()),
        artifact_id=str(uuid.uuid4()),
        source_sha256="a" * 64,
        action="issue",
        analysis_allowed=True,
        style_use_allowed=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    approval_id = str(uuid.uuid4())
    record = {
        "approval_id": approval_id,
        "status": "pending",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "created_at": datetime.now(timezone.utc),
        "intent": "writing_style.document_consent.issue",
        "risk_level": "high",
        "reason_codes": [],
    }
    service = SimpleNamespace(
        initiate_document_consent=AsyncMock(return_value=record),
        revoke_stored_document_consent=AsyncMock(return_value=True),
        get_document_consent_revocation_scope=AsyncMock(return_value=(
            {**record, "status": "consumed"}, scope,
        )),
        list_document_author_draft_profiles=AsyncMock(return_value=[{
            "profile_id": scope.profile_id, "label": "Author draft", "kind": "personal",
        }]),
        get_document_consent_confirmation=AsyncMock(return_value=(record, scope)),
        get_document_consent_review=AsyncMock(return_value=(
            record, scope, {
                "name": "my-author-source.txt",
                "bytes": 120,
                "mime_type": "text/plain",
            },
        )),
        recover_stored_document_consent_receipt=AsyncMock(
            return_value=str(uuid.uuid4()),
        ),
        confirm_stored_document_consent=AsyncMock(
            return_value={**record, "status": "approved"},
        ),
        issue_stored_document_consent=AsyncMock(return_value=str(uuid.uuid4())),
    )
    monkeypatch.setattr(routes, "get_approval_service", lambda: service)
    return app, approval_id, scope, service


async def test_preview_is_source_bound_and_does_not_accept_request_scopes(
    client_and_service,
):
    app, approval_id, scope, service = client_and_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/approvals/document-consent/" + approval_id,
            headers={"Authorization": "Bearer test-author"},
        )
    assert response.status_code == 200
    assert response.json()["source_sha256"] == scope.source_sha256
    assert response.json()["artifact_id"] == scope.artifact_id
    assert response.json()["source_name"] == "my-author-source.txt"
    assert response.json()["source_bytes"] == 120
    assert response.json()["source_mime_type"] == "text/plain"
    kwargs = service.get_document_consent_review.await_args.kwargs
    assert kwargs["request"].headers["authorization"] == "Bearer test-author"
    assert service.get_document_consent_review.await_args.args == (approval_id,)


async def test_confirmation_requires_strict_explicit_true(client_and_service):
    app, approval_id, _, service = client_and_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        for value in ("true", 1, "yes"):
            response = await client.post(
                "/api/approvals/document-consent/" + approval_id + "/confirm",
                json={"confirmed": value},
            )
            assert response.status_code == 422
        response = await client.post(
            "/api/approvals/document-consent/" + approval_id + "/confirm",
            json={"confirmed": True},
        )
    assert response.status_code == 200
    service.confirm_stored_document_consent.assert_awaited_once()
    assert service.confirm_stored_document_consent.await_args.kwargs["confirmed"] is True
    assert "scope" not in service.confirm_stored_document_consent.await_args.kwargs
    service.issue_stored_document_consent.assert_not_awaited()


async def test_receipt_route_only_sends_server_approval_identity(client_and_service):
    app, approval_id, _, service = client_and_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/approvals/document-consent/" + approval_id + "/issue",
            json={
                "source_sha256": "b" * 64,
                "style_use_allowed": True,
                "actor_id": str(uuid.uuid4()),
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "issued"
    service.issue_stored_document_consent.assert_awaited_once()
    assert service.issue_stored_document_consent.await_args.args == (approval_id,)
    kwargs = service.issue_stored_document_consent.await_args.kwargs
    assert "source_sha256" not in kwargs
    assert "actor_id" not in kwargs
    assert "style_use_allowed" not in kwargs
    assert kwargs["correlation_id"]


async def test_scope_and_state_failures_do_not_return_success(client_and_service):
    app, approval_id, _, service = client_and_service
    service.get_document_consent_review.side_effect = ApprovalScopeError("denied")
    service.confirm_stored_document_consent.side_effect = ApprovalScopeError("denied")
    service.issue_stored_document_consent.side_effect = ApprovalStateError("not issued")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        preview = await client.get("/api/approvals/document-consent/" + approval_id)
        confirm = await client.post(
            "/api/approvals/document-consent/" + approval_id + "/confirm",
            json={"confirmed": True},
        )
        receipt = await client.post(
            "/api/approvals/document-consent/" + approval_id + "/issue",
        )
    assert preview.status_code == 403
    assert confirm.status_code == 403
    assert receipt.status_code == 409
    assert receipt.json()["detail"] == "Document receipt not issued"


async def test_receipt_recovery_never_mints_or_infers_receipt(client_and_service):
    app, approval_id, _, service = client_and_service
    receipt = service.recover_stored_document_consent_receipt.return_value
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        recovered = await client.get(
            "/api/approvals/document-consent/" + approval_id + "/receipt",
            headers={"Authorization": "Bearer test-author"},
        )
        assert recovered.status_code == 200
        assert recovered.json()["receipt_id"] == receipt
        kwargs = service.recover_stored_document_consent_receipt.await_args.kwargs
        assert kwargs["request"].headers["authorization"] == "Bearer test-author"
        service.recover_stored_document_consent_receipt.return_value = None
        missing = await client.get(
            "/api/approvals/document-consent/" + approval_id + "/receipt",
        )
        assert missing.status_code == 404
        assert "receipt_id" not in missing.json()
        service.recover_stored_document_consent_receipt.side_effect = ApprovalScopeError("denied")
        denied = await client.get(
            "/api/approvals/document-consent/" + approval_id + "/receipt",
        )
        assert denied.status_code == 403
    service.issue_stored_document_consent.assert_not_awaited()


async def test_initiation_accepts_only_source_selectors(client_and_service):
    app, _, scope, service = client_and_service
    payload = {
        "profile_id": scope.profile_id,
        "artifact_id": scope.artifact_id,
        "style_use_allowed": False,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        for forbidden in (
            {"source_sha256": "b" * 64},
            {"author_actor_id": str(uuid.uuid4())},
            {"session_id": "forged-session"},
            {"tenant_id": str(uuid.uuid4())},
            {"expires_at": "2099-01-01T00:00:00Z"},
            {"analysis_allowed": True},
        ):
            denied = await client.post(
                "/api/approvals/document-consent/initiate",
                json={**payload, **forbidden},
            )
            assert denied.status_code == 422
        malformed = await client.post(
            "/api/approvals/document-consent/initiate",
            json={**payload, "style_use_allowed": "true"},
        )
        assert malformed.status_code == 422
        success = await client.post(
            "/api/approvals/document-consent/initiate",
            json=payload,
            headers={"Authorization": "Bearer dedicated-author"},
        )
    assert success.status_code == 200
    assert success.json()["status"] == "pending"
    kwargs = service.initiate_document_consent.await_args.kwargs
    assert kwargs["request"].headers["authorization"] == "Bearer dedicated-author"
    assert kwargs["profile_id"] == scope.profile_id
    assert kwargs["artifact_id"] == scope.artifact_id
    assert kwargs["style_use_allowed"] is False
    assert "source_sha256" not in kwargs
    assert "tenant_id" not in kwargs
    assert "session_id" not in kwargs
    service.issue_stored_document_consent.assert_not_awaited()


async def test_initiation_denial_has_no_approval_or_receipt_claim(client_and_service):
    app, _, scope, service = client_and_service
    service.initiate_document_consent.side_effect = ApprovalScopeError("source unavailable")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        denied = await client.post(
            "/api/approvals/document-consent/initiate",
            json={
                "profile_id": scope.profile_id,
                "artifact_id": scope.artifact_id,
                "style_use_allowed": True,
            },
        )
    assert denied.status_code == 403
    assert "approval_id" not in denied.json()
    service.issue_stored_document_consent.assert_not_awaited()


async def test_draft_profile_inventory_is_only_server_authenticated_metadata(
    client_and_service,
):
    app, _, scope, service = client_and_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        result = await client.get(
            "/api/approvals/document-consent/profiles",
            headers={"Authorization": "Bearer author-inventory"},
        )
        assert result.status_code == 200
        assert result.json() == [{
            "profile_id": scope.profile_id,
            "label": "Author draft",
            "kind": "personal",
        }]
        called = service.list_document_author_draft_profiles.await_args.kwargs
        assert called["request"].headers["authorization"] == "Bearer author-inventory"
        assert "tenant_id" not in called
        assert "actor_id" not in called

        service.list_document_author_draft_profiles.side_effect = ApprovalScopeError(
            "denied"
        )
        denied = await client.get("/api/approvals/document-consent/profiles")
        assert denied.status_code == 403
        assert not isinstance(denied.json(), list)


async def test_revocation_requires_explicit_true_and_never_accepts_scoped_inputs(
    client_and_service,
):
    app, approval_id, _, service = client_and_service
    url = "/api/approvals/document-consent/" + approval_id + "/revoke"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        for payload in (
            {"confirmed": False},
            {"confirmed": "true"},
            {"confirmed": 1},
            {"confirmed": True, "receipt_id": str(uuid.uuid4())},
            {"confirmed": True, "tenant_id": str(uuid.uuid4())},
        ):
            response = await client.post(url, json=payload)
            assert response.status_code in (403, 422)
        service.revoke_stored_document_consent.assert_not_awaited()
        result = await client.post(
            url,
            json={"confirmed": True},
            headers={"Authorization": "Bearer verified-author"},
        )
        assert result.status_code == 200
        assert result.json() == {"approval_id": approval_id, "status": "revoked"}
        kwargs = service.revoke_stored_document_consent.await_args.kwargs
        assert kwargs["request"].headers["authorization"] == "Bearer verified-author"
        assert kwargs["confirmed"] is True
        assert "actor_id" not in kwargs
        assert "receipt_id" not in kwargs
        service.revoke_stored_document_consent.side_effect = ApprovalStateError(
            "not current"
        )
        unavailable = await client.post(url, json={"confirmed": True})
        assert unavailable.status_code == 409
        assert unavailable.json()["detail"] == "Author revocation not recorded"


async def test_revocation_review_uses_verified_author_scope_not_source_bytes(
    client_and_service,
):
    app, approval_id, scope, service = client_and_service
    url = "/api/approvals/document-consent/" + approval_id + "/revoke-review"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            url, headers={"Authorization": "Bearer refreshed-author"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "approval_id": approval_id,
            "status": "consumed",
            "profile_id": scope.profile_id,
            "artifact_id": scope.artifact_id,
            "source_sha256": scope.source_sha256,
        }
        kwargs = service.get_document_consent_revocation_scope.await_args.kwargs
        assert kwargs["request"].headers["authorization"] == "Bearer refreshed-author"
        assert "source" not in kwargs
        assert "actor_id" not in kwargs

        service.get_document_consent_revocation_scope.side_effect = ApprovalScopeError(
            "foreign author"
        )
        denied = await client.get(url)
        assert denied.status_code == 403
        assert "source_sha256" not in denied.json()


async def test_revocation_review_does_not_present_unconsumed_approval(
    client_and_service,
):
    app, approval_id, _, service = client_and_service
    service.get_document_consent_revocation_scope.side_effect = ApprovalStateError(
        "not issued"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/approvals/document-consent/" + approval_id + "/revoke-review",
        )
    assert response.status_code == 409
    assert "source_sha256" not in response.json()
    assert "receipt_id" not in response.json()
