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
        tenant_id="tenant-a", role=UserRole.ADMIN, status=UserStatus.ACTIVE,
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


def test_admin_user_filters_reject_invalid_enums_at_request_validation():
    from fastapi import FastAPI
    from ai_karen_engine.api_routes.admin.users import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    parameters = next(
        route["get"]["parameters"]
        for route in schema["paths"].values()
        if route.get("get", {}).get("operationId", "").startswith("list_admin_users")
    )
    role = next(item for item in parameters if item["name"] == "role")
    status = next(item for item in parameters if item["name"] == "status")
    assert role["schema"]["anyOf"][0]["$ref"].endswith("/UserRole")
    assert status["schema"]["anyOf"][0]["$ref"].endswith("/UserStatus")


def test_admin_user_creation_rejects_invalid_roles():
    from pydantic import ValidationError
    from ai_karen_engine.api_routes.admin.users import AdminUserCreateRequest

    with pytest.raises(ValidationError):
        AdminUserCreateRequest(
            email="new@example.com", password="test-password",
            full_name="New User", tenant_id="tenant-a",
            roles=["super_admin"],
        )
