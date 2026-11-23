from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHAT_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
ERROR_MIDDLEWARE = ROOT / "src/ai_karen_engine/middleware/intelligent_error_handler.py"


def test_chat_transport_does_not_replace_unexpected_runtime_errors() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert 'raise HTTPException(status_code=500, detail="Internal server error")' not in source
    assert 'context="unexpected_error"' not in source


def test_chat_transport_keeps_expected_validation_translation() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert source.count("except HTTPException:") >= 2
    assert source.count("except ValueError as exc:") >= 2
    assert 'raise HTTPException(status_code=400, detail="Invalid chat request") from exc' in source
    assert "logger.exception(" not in source
    assert "error=str(exc)" not in source


def test_global_error_middleware_owns_unexpected_exception_translation() -> None:
    source = ERROR_MIDDLEWARE.read_text(encoding="utf-8")

    assert "except Exception as exc:" in source
    # Capturing raw tracebacks is not required for unexpected transport errors.
    # SQLAlchemy exception tracebacks may include bound private user data.
    assert "traceback.format_exc()" not in source
    assert 'error_message = "Internal server error"' in source
    assert "logger.exception(" not in source
    assert "error_type = type(exc).__name__" in source



@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "method", "body", "error_kind", "status", "detail"),
    [
        ("/chat/approvals/{id}/resume", "POST", None, "scope", 403, "Approval scope denied"),
        ("/chat/approvals/{id}/resume", "POST", None, "state", 409, "Approval cannot be resumed"),
        ("/chat/approvals/{id}/resume", "POST", None, "missing", 404, "Approval not found"),
        ("/api/approvals/", "GET", None, "scope", 403, "Approval access denied"),
        ("/api/approvals/{id}", "GET", None, "scope", 403, "Approval access denied"),
        ("/api/approvals/{id}/decision", "POST", {"decision": "approved"}, "scope", 403, "Approval access denied"),
        ("/api/approvals/{id}/decision", "POST", {"decision": "approved"}, "state", 409, "Approval state conflict"),
        ("/api/approvals/document-consent/{id}/confirm", "POST", {"confirmed": True}, "state", 409, "Document confirmation conflict"),
        ("/api/approvals/", "GET", None, "sql", 500, "Failed to list approvals"),
        ("/api/approvals/{id}/decision", "POST", {"decision": "rejected"}, "sql", 500, "Failed to decide approval"),
    ],
)
async def test_approval_http_transports_redact_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    route: str,
    method: str,
    body: dict | None,
    error_kind: str,
    status: int,
    detail: str,
) -> None:
    import logging
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import StatementError

    from ai_karen_engine.api_routes.automation import approvals
    from ai_karen_engine.api_routes.chat import runtime
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.services.approvals import (
        ApprovalNotFoundError,
        ApprovalScopeError,
        ApprovalStateError,
    )

    sentinel = "PRIVATE_APPROVAL_BOUND_SQL_PARAMETER"
    sql_error = StatementError(
        "private approval database operation",
        "SELECT :private_value",
        {"private_value": sentinel},
        RuntimeError("private approval driver"),
    )
    injected = {
        "scope": ApprovalScopeError(sentinel),
        "state": ApprovalStateError(sentinel),
        "missing": ApprovalNotFoundError(sentinel),
        "sql": sql_error,
    }[error_kind]

    class FailingApprovals:
        async def build_resume_request(self, *_args, **_kwargs):
            raise injected

        async def list_actionable(self, **_kwargs):
            raise injected

        async def get(self, *_args, **_kwargs):
            raise injected

        async def decide(self, *_args, **_kwargs):
            raise injected

        async def confirm_stored_document_consent(self, *_args, **_kwargs):
            raise injected

    user = UserData(
        user_id="11111111-1111-4111-8111-111111111111",
        tenant_id="22222222-2222-4222-8222-222222222222",
        permissions=["chat:execute"],
    )
    app = FastAPI()
    app.include_router(runtime.router)
    app.include_router(approvals.router)
    app.dependency_overrides[runtime.bypass_user_context_func] = lambda: dict(user)
    app.dependency_overrides[approvals.get_current_user] = lambda: user
    monkeypatch.setattr(runtime, "get_approval_service", FailingApprovals)
    monkeypatch.setattr(approvals, "get_approval_service", FailingApprovals)
    path = route.replace("{id}", "11111111-1111-4111-8111-111111111111")

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.request(method, path, json=body)

    assert response.status_code == status
    assert response.json()["detail"] == detail
    for forbidden in (sentinel, "SELECT :private_value", "private approval driver"):
        assert forbidden not in response.text + caplog.text
    assert all(
        record.exc_info is None for record in caplog.records
        if record.name in (approvals.__name__, runtime.__name__)
    )


def test_approval_transport_has_no_raw_exception_or_traceback_paths() -> None:
    root = ROOT / "src/ai_karen_engine/api_routes"
    for path in (
        root / "chat/runtime.py",
        root / "automation/approvals.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "detail=str(exc)" not in source
    approvals = (root / "automation/approvals.py").read_text(encoding="utf-8")
    assert "logger.exception(" not in approvals
