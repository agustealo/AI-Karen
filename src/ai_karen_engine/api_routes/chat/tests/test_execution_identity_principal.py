"""All chat transport adapters must carry the authenticated ingress principal."""

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat.execution_identity import (
    build_chat_execution_context,
)


def _context(user):
    return build_chat_execution_context(
        user=user,
        session_id="session-1",
        conversation_id="conversation-1",
        request_id="request-1",
        correlation_id="correlation-1",
    )


def test_copilot_transport_carries_verifiable_authenticated_principal():
    context = _context({
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "roles": ["user"],
        "permissions": ["chat:write"],
    })
    principal = context.require_authenticated_user()
    assert principal.user_id == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.permissions == ["chat:write"]


def test_copilot_transport_rejects_inactive_or_unverified_principal():
    for field in ("is_active", "is_verified"):
        context = _context({
            "user_id": "user-1", "tenant_id": "tenant-1", field: False,
        })
        with pytest.raises(PermissionError, match="authenticated_principal_inactive"):
            context.require_authenticated_user()


def test_copilot_transport_rejects_missing_tenant_before_runtime():
    with pytest.raises(HTTPException) as exc_info:
        _context({"user_id": "user-1", "tenant_id": ""})
    assert exc_info.value.status_code == 401


def test_copilot_transport_does_not_accept_changed_runtime_identity():
    context = _context({"user_id": "user-1", "tenant_id": "tenant-1"})
    context.user_id = "other-user"
    with pytest.raises(PermissionError, match="authenticated_principal_scope_mismatch"):
        context.require_authenticated_user()
