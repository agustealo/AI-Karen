"""Regression proof for admin user route imports and canonical enums."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.api_routes.admin.users import (
    create_admin_user,
    list_admin_users,
)
from ai_karen_engine.services.auth.auth_service import UserRole, UserStatus


@pytest.mark.asyncio
async def test_admin_user_list_uses_canonical_role_and_status():
    class UserService:
        async def list_users(self, *, user_filter, operator_tenant_id, operator_id):
            assert user_filter.role is UserRole.ADMIN
            assert user_filter.status is UserStatus.ACTIVE
            assert operator_tenant_id == "tenant-a"
            assert operator_id == "operator"
            return []

    result = await list_admin_users(
        current_user={"user_id": "operator", "tenant_id": "tenant-a"},
        service=UserService(),
        tenant_id="tenant-a", role="admin", status="active",
        search=None, limit=10, offset=0,
    )
    assert result.users == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_admin_user_create_uses_canonical_role():
    class UserService:
        async def create_user(self, **kwargs):
            assert kwargs["roles"] == [UserRole.ADMIN]
            assert kwargs["operator_tenant_id"] == "tenant-a"
            assert kwargs["operator_id"] == "operator"
            return SimpleNamespace(
                id="created-user", email=kwargs["email"],
                full_name=kwargs["full_name"], tenant_id=kwargs["tenant_id"],
                roles=kwargs["roles"],
            )

    from ai_karen_engine.api_routes.admin.users import AdminUserCreateRequest

    result = await create_admin_user(
        request=AdminUserCreateRequest(
            email="new@example.com", password="test-password",
            full_name="New User", tenant_id="tenant-a", roles=["admin"],
        ),
        current_user={"user_id": "operator", "tenant_id": "tenant-a"},
        service=UserService(),
    )
    assert result["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_admin_user_update_persists_through_canonical_auth():
    from ai_karen_engine.services.admin.admin_user_service import AdminUserService

    calls = []
    class CanonicalAuth:
        async def get_user_by_id(self, user_id):
            return SimpleNamespace(id=user_id, tenant_id="tenant-a")

        async def update_user(self, user_id, **fields):
            calls.append(("update", user_id, fields))

    service = AdminUserService.__new__(AdminUserService)
    service._auth_service = CanonicalAuth()
    service._audit_mutation = lambda **kwargs: calls.append(("audit", kwargs))
    result = await service.update_user(
        "user-a", {"full_name": "New Name", "roles": ["admin"]},
        operator_tenant_id="tenant-a", operator_id="operator",
    )
    assert result is True
    assert calls[0] == (
        "update", "user-a", {"full_name": "New Name", "roles": ["admin"]}
    )
    assert calls[-1][0] == "audit"


@pytest.mark.asyncio
async def test_admin_user_delete_deactivates_and_revokes_sessions():
    from ai_karen_engine.services.admin.admin_user_service import AdminUserService

    calls = []
    class CanonicalAuth:
        async def get_user_by_id(self, user_id):
            return SimpleNamespace(id=user_id, tenant_id="tenant-a")

        async def set_user_status(self, user_id, is_active, *, reason):
            calls.append(("status", user_id, is_active, reason))

    service = AdminUserService.__new__(AdminUserService)
    service._auth_service = CanonicalAuth()
    service._audit_mutation = lambda **kwargs: calls.append(("audit", kwargs))
    assert await service.delete_user(
        "user-a", operator_tenant_id="tenant-a", operator_id="operator"
    )
    assert calls[0] == ("status", "user-a", False, "admin_user_deleted")
    assert calls[-1][0] == "audit"


@pytest.mark.asyncio
async def test_admin_user_cross_tenant_mutation_never_reaches_auth_write():
    from ai_karen_engine.services.admin.admin_user_service import AdminUserService

    class CanonicalAuth:
        async def get_user_by_id(self, user_id):
            return SimpleNamespace(id=user_id, tenant_id="tenant-b")

        async def update_user(self, *args, **kwargs):
            pytest.fail("cross-tenant write reached canonical auth")

        async def set_user_status(self, *args, **kwargs):
            pytest.fail("cross-tenant deactivation reached canonical auth")

    service = AdminUserService.__new__(AdminUserService)
    service._auth_service = CanonicalAuth()
    service._audit_mutation = lambda **kwargs: None
    with pytest.raises(PermissionError):
        await service.update_user(
            "user-b", {"full_name": "Blocked"}, operator_tenant_id="tenant-a"
        )
    with pytest.raises(PermissionError):
        await service.delete_user("user-b", operator_tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_admin_user_deactivation_uses_canonical_session_revocation():
    from ai_karen_engine.services.admin.admin_user_service import AdminUserService

    calls = []
    class CanonicalAuth:
        async def get_user_by_id(self, user_id):
            return SimpleNamespace(id=user_id, tenant_id="tenant-a")

        async def set_user_status(self, user_id, is_active, *, reason):
            calls.append((user_id, is_active, reason))

    service = AdminUserService.__new__(AdminUserService)
    service._auth_service = CanonicalAuth()
    service._audit_mutation = lambda **kwargs: None
    assert await service.update_user(
        "user-a", {"is_active": False}, operator_tenant_id="tenant-a"
    )
    assert calls == [("user-a", False, "admin_user_deactivated")]


@pytest.mark.asyncio
async def test_admin_user_route_converts_cross_tenant_denial_to_403():
    from fastapi import HTTPException
    from ai_karen_engine.api_routes.admin.users import get_admin_user

    class DenyingService:
        async def get_user(self, *args, **kwargs):
            raise PermissionError("tenant-b secret")

    with pytest.raises(HTTPException) as raised:
        await get_admin_user(
            "user-b",
            current_user={"user_id": "operator", "tenant_id": "tenant-a"},
            service=DenyingService(),
        )
    assert raised.value.status_code == 403
    assert "tenant-b" not in str(raised.value.detail)


@pytest.mark.asyncio
async def test_admin_user_rejects_composite_deactivation_before_writes():
    from ai_karen_engine.services.admin.admin_user_service import AdminUserService

    class CanonicalAuth:
        async def get_user_by_id(self, user_id):
            return SimpleNamespace(id=user_id, tenant_id="tenant-a")

        async def update_user(self, *args, **kwargs):
            pytest.fail("partial profile mutation")

        async def set_user_status(self, *args, **kwargs):
            pytest.fail("partial deactivation")

    service = AdminUserService.__new__(AdminUserService)
    service._auth_service = CanonicalAuth()
    with pytest.raises(ValueError, match="separately"):
        await service.update_user(
            "user-a", {"full_name": "Changed", "is_active": False},
            operator_tenant_id="tenant-a",
        )
