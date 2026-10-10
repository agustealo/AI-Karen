"""Admin mutations reuse canonical auth persistence with tenant and audit guards."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.admin.admin_user_service import AdminUserService
from ai_karen_engine.services.auth.auth_service import UserRole


class AuthStub:
    def __init__(self):
        self.calls = []
        self.user = SimpleNamespace(id="user-1", tenant_id="tenant-a")

    async def get_user_by_id(self, user_id):
        return self.user

    async def update_user(self, user_id, **updates):
        self.calls.append(("update", user_id, updates))
        return self.user

    async def set_user_status(self, user_id, is_active, *, reason=None):
        self.calls.append(("status", user_id, is_active, reason))
        return self.user


@pytest.mark.asyncio
async def test_update_uses_canonical_auth_and_audits(monkeypatch):
    auth = AuthStub()
    service = AdminUserService(auth)
    audits = []
    monkeypatch.setattr(service, "_audit_mutation", lambda **kw: audits.append(kw))
    assert await service.update_user(
        "user-1", {"roles": ["admin"], "full_name": "Updated"},
        operator_tenant_id="tenant-a", operator_id="operator",
    )
    assert auth.calls == [
        ("update", "user-1", {"roles": [UserRole.ADMIN], "full_name": "Updated"})
    ]
    assert audits[0]["operator_id"] == "operator"


@pytest.mark.asyncio
async def test_delete_deactivates_and_audits(monkeypatch):
    auth = AuthStub()
    service = AdminUserService(auth)
    audits = []
    monkeypatch.setattr(service, "_audit_mutation", lambda **kw: audits.append(kw))
    assert await service.delete_user(
        "user-1", operator_tenant_id="tenant-a", operator_id="operator"
    )
    assert auth.calls == [("status", "user-1", False, "admin_deactivated")]
    assert audits[0]["action"] == "delete"


@pytest.mark.asyncio
async def test_cross_tenant_mutations_fail_closed(monkeypatch):
    auth = AuthStub()
    service = AdminUserService(auth)
    monkeypatch.setattr(service, "_audit_mutation", lambda **kw: None)
    with pytest.raises(PermissionError):
        await service.update_user(
            "user-1", {"full_name": "Unauthorized"}, operator_tenant_id="tenant-b"
        )
    with pytest.raises(PermissionError):
        await service.delete_user("user-1", operator_tenant_id="tenant-b")
    assert auth.calls == []


@pytest.mark.asyncio
async def test_unknown_update_fields_never_reach_auth(monkeypatch):
    auth = AuthStub()
    service = AdminUserService(auth)
    monkeypatch.setattr(service, "_audit_mutation", lambda **kw: None)
    with pytest.raises(ValueError):
        await service.update_user("user-1", {"tenant_id": "tenant-b"}, operator_tenant_id="tenant-a")
    assert auth.calls == []
