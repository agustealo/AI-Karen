"""Admin user listing count, tenant and paging contract."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.api_routes.admin.users import list_admin_users
from ai_karen_engine.services.admin.admin_user_service import AdminUserFilter, AdminUserService


@pytest.mark.asyncio
async def test_admin_list_reports_filtered_total_not_page_length():
    class Service:
        async def list_users_page(self, **kwargs):
            assert kwargs["user_filter"].offset == 20
            return [], 35

    response = await list_admin_users(
        current_user={"user_id": "operator", "tenant_id": "tenant-a"},
        service=Service(), tenant_id="tenant-a", role=None, status=None,
        search=None, limit=10, offset=20,
    )
    assert response.users == []
    assert response.total == 35
    assert response.limit == 10
    assert response.offset == 20


@pytest.mark.asyncio
async def test_admin_service_requires_tenant_before_query():
    class Auth:
        async def list_users_page(self, **kwargs):
            raise AssertionError("tenantless query should not execute")

    service = AdminUserService(Auth())
    with pytest.raises(PermissionError):
        await service.list_users_page(AdminUserFilter(), operator_tenant_id=None)


@pytest.mark.asyncio
async def test_admin_service_preserves_filters_and_total():
    class Auth:
        async def list_users_page(self, **kwargs):
            assert kwargs["tenant_id"] == "tenant-a"
            assert kwargs["search"] == "hello"
            assert kwargs["limit"] == 5
            assert kwargs["offset"] == 10
            return [], 27

    service = AdminUserService(Auth())
    service._audit_mutation = lambda **kwargs: None
    page, total = await service.list_users_page(
        AdminUserFilter(search="hello", limit=5, offset=10),
        operator_tenant_id="tenant-a", operator_id="operator",
    )
    assert page == []
    assert total == 27
