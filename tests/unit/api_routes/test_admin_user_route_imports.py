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
        async def list_users_page(self, *, user_filter, operator_tenant_id, operator_id):
            assert user_filter.role is UserRole.ADMIN
            assert user_filter.status is UserStatus.ACTIVE
            assert operator_tenant_id == "tenant-a"
            assert operator_id == "operator"
            return [], 0

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
@pytest.mark.parametrize("roles,allowed", [(["user"], False), (["admin"], False),
                                            (["super_admin"], True)])
async def test_platform_tenant_permission_requires_super_admin(roles, allowed):
    from fastapi import HTTPException
    from ai_karen_engine.api_routes.admin.tenants import require_platform_tenant_permission
    from ai_karen_engine.auth.rbac_middleware import Permission

    guard = require_platform_tenant_permission(Permission.ADMIN_TENANTS_MANAGE)
    principal = {"user_id": "operator", "tenant_id": "tenant-a", "roles": roles}
    if allowed:
        assert await guard(principal) is principal
    else:
        with pytest.raises(HTTPException) as exc:
            await guard(principal)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_tenant_create_requires_credentials_and_redacts_secret(monkeypatch):
    from pydantic import ValidationError
    from ai_karen_engine.api_routes.admin import tenants

    with pytest.raises(ValidationError):
        tenants.AdminTenantCreateRequest(name="Tenant", slug="tenant", admin_email="a@example.test")

    class Service:
        async def create_tenant(self, **kwargs):
            assert kwargs["admin_password"] == "StrongPassword1!"
            assert kwargs["admin_full_name"] == "Tenant Admin"
            assert kwargs["operator_id"] == "operator"
            config = kwargs["config"]
            return SimpleNamespace(id="created", name=config.name, slug=config.slug, settings={})

    request = tenants.AdminTenantCreateRequest(
        name="Tenant", slug="tenant", admin_email="a@example.test",
        admin_password="StrongPassword1!", admin_full_name="Tenant Admin",
    )
    assert "StrongPassword1!" not in repr(request)
    monkeypatch.setattr(tenants, "get_admin_tenant_service", lambda: Service())
    result = await tenants.create_admin_tenant(
        request, current_user={"user_id": "operator", "roles": ["super_admin"]},
    )
    assert result["tenant_id"] == "created"
    assert "admin_password" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "account", "scope", "audit_scope", "audit_flush", "commit"])
async def test_tenant_creation_uses_one_transaction(monkeypatch, failure):
    import uuid
    from contextlib import asynccontextmanager
    from ai_karen_engine.auth import auth_service
    from ai_karen_engine.database.models import AuditLog
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager
    from ai_karen_engine.persistence.postgres import transactions

    operator_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())
    events = []

    class Session:
        audit = None

        def add(self, row):
            if isinstance(row, AuditLog):
                self.audit = row
                events.append("audit")
            else:
                self.tenant = row
                events.append("tenant")

        async def flush(self):
            if self.audit is not None:
                events.append("audit_flush")
                if failure == "audit_flush":
                    raise RuntimeError("audit write failed")
            else:
                self.tenant.id = uuid.uuid4()
                events.append("flush")

    session = Session()

    class Client:
        @asynccontextmanager
        async def get_async_session(self):
            try:
                yield session
                if failure == "commit":
                    raise RuntimeError("commit failed")
                events.append("commit")
            except Exception:
                events.append("rollback")
                raise

        def create_tenant_schema(self, *args):
            raise AssertionError("Shared tables are migration owned")

        def drop_tenant_schema(self, *args):
            raise AssertionError("Failed creation must never drop a schema")

    class Auth:
        async def create_user_in_transaction(self, supplied, **kwargs):
            assert supplied is session
            assert kwargs["password"] == "StrongPassword1!"
            assert kwargs["tenant_id"] == str(session.tenant.id)
            assert kwargs["roles"] == ["admin", "user"]
            assert kwargs["is_verified"] is True
            events.append("account")
            if failure == "account":
                raise ValueError("duplicate account")
            return SimpleNamespace(
                id=admin_id, tenant_id="wrong" if failure == "scope" else kwargs["tenant_id"],
            )

    async def get_auth():
        return Auth()

    async def apply_context(supplied, *, tenant_id, user_id):
        assert supplied is session
        assert tenant_id == str(session.tenant.id)
        assert user_id == operator_id
        events.append("audit_scope")
        if failure == "audit_scope":
            raise RuntimeError("audit scope failed")

    monkeypatch.setattr(auth_service, "get_auth_service", get_auth)
    monkeypatch.setattr(transactions, "apply_authenticated_transaction_context", apply_context)
    manager = TenantManager(Client())

    async def create():
        return await manager.create_tenant(
            TenantConfig("Tenant", "tenant"), "a@example.test",
            admin_password="StrongPassword1!", admin_full_name="Tenant Admin",
            operator_id=operator_id,
        )

    expected = ["tenant", "flush", "account"]
    if failure not in {"account", "scope"}:
        expected.append("audit_scope")
        if failure != "audit_scope":
            expected.extend(["audit", "audit_flush"])
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            await create()
        assert events == [*expected, "rollback"]
    else:
        assert await create() is session.tenant
        assert events == [*expected, "commit"]
        assert session.audit.tenant_id == str(session.tenant.id)
        assert session.audit.user_id == operator_id
        assert session.audit.actor_type == "user"
        assert session.audit.action == "admin_tenant_create"
        assert session.audit.resource_type == "tenant"
        assert session.audit.resource_id == str(session.tenant.id)
        assert session.audit.details == {"initial_admin_user_id": admin_id}
    assert not manager._tenant_cache


@pytest.mark.asyncio
@pytest.mark.parametrize("operator_id", [None, "", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
async def test_tenant_creation_rejects_invalid_operator_before_database(operator_id):
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager

    with pytest.raises(ValueError, match="operator"):
        await TenantManager(None).create_tenant(
            TenantConfig("Tenant", "tenant"), "a@example.test",
            admin_password="StrongPassword1!", admin_full_name="Tenant Admin",
            operator_id=operator_id,
        )


@pytest.mark.asyncio
async def test_tenant_creation_rejects_privilege_escalation_before_database():
    from ai_karen_engine.database.tenant_manager import TenantConfig, TenantManager

    manager = TenantManager(None)
    with pytest.raises(ValueError, match="roles"):
        await manager.create_tenant(
            TenantConfig("Tenant", "tenant"), "a@example.test", ["super_admin"],
            admin_password="StrongPassword1!", admin_full_name="Tenant Admin",
            operator_id="11111111-1111-4111-8111-111111111111",
        )
