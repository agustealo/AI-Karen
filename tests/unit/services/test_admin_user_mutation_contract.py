"""Admin user mutation contract: canonical writes, tenant guards, and audits."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.admin.admin_user_service import AdminUserService


class AuthStub:
    def __init__(self):
        self.calls = []
        self.user = SimpleNamespace(id="other", tenant_id="tenant-a")

    async def get_user_by_id(self, user_id):
        return self.user if user_id == "other" else None

    async def update_user(self, user_id, **kwargs):
        self.calls.append(("update", user_id, kwargs))
        return self.user

    async def set_user_status(self, user_id, enabled, *, reason):
        self.calls.append(("status", user_id, enabled, reason))
        return self.user


def service_with_audit(auth):
    service = AdminUserService(auth)
    events = []
    service._audit_mutation = lambda **kwargs: events.append(kwargs)
    return service, events


@pytest.mark.asyncio
async def test_update_persists_through_canonical_auth():
    auth = AuthStub()
    service, events = service_with_audit(auth)
    assert await service.update_user(
        "other", {"full_name": "Updated", "roles": ["admin"], "is_active": False},
        operator_tenant_id="tenant-a", operator_id="operator",
    )
    assert auth.calls == [
        ("update", "other", {"full_name": "Updated", "roles": ["admin"]}),
        ("status", "other", False, "admin_account_status_change"),
    ]
    assert events[-1]["action"] == "update"


@pytest.mark.asyncio
async def test_deactivate_uses_canonical_revoking_status_path():
    auth = AuthStub()
    service, events = service_with_audit(auth)
    assert await service.delete_user("other", operator_tenant_id="tenant-a", operator_id="operator")
    assert auth.calls == [("status", "other", False, "admin_account_deactivation")]
    assert events[-1]["action"] == "deactivate"


@pytest.mark.asyncio
async def test_cross_tenant_mutation_denied_before_write():
    auth = AuthStub()
    service, events = service_with_audit(auth)
    with pytest.raises(PermissionError):
        await service.update_user("other", {"full_name": "Denied"}, operator_tenant_id="tenant-b")
    assert auth.calls == []
    assert events == []


@pytest.mark.asyncio
async def test_self_deactivation_denied():
    auth = AuthStub()
    auth.user.id = "other"
    service, events = service_with_audit(auth)
    with pytest.raises(PermissionError):
        await service.delete_user("other", operator_tenant_id="tenant-a", operator_id="other")
    assert not auth.calls
    assert not events


@pytest.mark.asyncio
async def test_invalid_update_rejected_before_write():
    auth = AuthStub()
    service, _ = service_with_audit(auth)
    with pytest.raises(ValueError):
        await service.update_user("other", {"tenant_id": "tenant-b"}, operator_tenant_id="tenant-a")
    assert not auth.calls
