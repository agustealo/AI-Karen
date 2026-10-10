"""Admin session listing must use durable auth without exposing credentials."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.admin.admin_user_service import AdminUserService


class AuthStub:
    def __init__(self):
        self.calls = []
        self._active_sessions = {"stale": object()}

    async def get_user_by_id(self, user_id):
        return SimpleNamespace(id=user_id, tenant_id="tenant-a")

    async def list_sessions(self, *, user_id, active_only, strict_errors):
        assert strict_errors is True
        self.calls.append((user_id, active_only))
        return [{
            "session_token": "durable-session-id",
            "user_id": user_id,
            "created_at": "2026-10-09T10:00:00",
            "last_accessed": None,
            "ip_address": "127.0.0.1",
            "user_agent": "test",
            "is_active": True,
            "access_token": "must-not-appear",
            "refresh_token": "must-not-appear",
            "device_fingerprint": "must-not-appear",
        }]


@pytest.mark.asyncio
async def test_admin_session_list_is_durable_and_redacted():
    auth = AuthStub()
    service = AdminUserService(auth)
    service._audit_mutation = lambda **kwargs: None
    sessions = await service.get_user_sessions(
        "user-a", operator_tenant_id="tenant-a", operator_id="operator"
    )
    assert auth.calls == [("user-a", True)]
    assert len(sessions) == 1
    assert sessions[0]["id"] == "durable-session-id"
    assert not ({"access_token", "refresh_token", "device_fingerprint"} & sessions[0].keys())


@pytest.mark.asyncio
async def test_cross_tenant_session_listing_rejected_before_query():
    auth = AuthStub()
    service = AdminUserService(auth)
    with pytest.raises(PermissionError):
        await service.get_user_sessions("user-a", operator_tenant_id="tenant-b")
    assert auth.calls == []


@pytest.mark.asyncio
async def test_session_read_error_propagates_instead_of_empty_success():
    class BrokenAuth(AuthStub):
        async def list_sessions(self, *, user_id, active_only, strict_errors):
            assert strict_errors is True
            raise RuntimeError("Session retrieval unavailable")

    service = AdminUserService(BrokenAuth())
    with pytest.raises(RuntimeError, match="Session retrieval unavailable"):
        await service.get_user_sessions("user-a", operator_tenant_id="tenant-a")
