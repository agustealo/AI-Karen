"""HTTP transport regression for admin user route error and response contracts.

Permissions are overridden solely to test transport. This suite does not
claim to prove production RBAC, durable DB behavior, or session revocation.
"""
from __future__ import annotations

import pytest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.admin.users import router


class AdminService:
    def __init__(self) -> None:
        self.calls = []

    async def list_users_page(self, *, user_filter, operator_tenant_id, operator_id):
        self.calls.append(("list", operator_tenant_id, operator_id))
        return [], 42

    async def update_user(self, user_id, updates, *, operator_tenant_id, operator_id):
        self.calls.append(("update", user_id, operator_tenant_id))
        if operator_tenant_id != "tenant-a":
            raise PermissionError("Cross-tenant denied")
        if "full_name" in updates and updates["full_name"] == "invalid":
            raise ValueError("Invalid name")
        return True

    async def delete_user(self, user_id, *, operator_tenant_id, operator_id):
        self.calls.append(("delete", user_id, operator_tenant_id))
        if operator_tenant_id != "tenant-a":
            raise PermissionError("Cross-tenant denied")
        return True


def build_client(service, *, actor_id="operator", tenant_id="tenant-a", authorized=True):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/admin/users"):
            for dep in route.dependant.dependencies:
                if dep.name == "current_user":
                    if authorized:
                        app.dependency_overrides[dep.call] = (
                            lambda: {"user_id": actor_id, "tenant_id": tenant_id}
                        )
                    else:
                        def reject():
                            raise HTTPException(status_code=403, detail="Forbidden")
                        app.dependency_overrides[dep.call] = reject
                elif dep.name == "service":
                    app.dependency_overrides[dep.call] = lambda: service
    return TestClient(app)


def test_list_total_comes_from_filtered_backend_count():
    service = AdminService()
    with build_client(service) as client:
        response = client.get("/api/admin/users/", params={"limit": 5, "offset": 15})
    assert response.status_code == 200
    assert response.json() == {"users": [], "total": 42, "limit": 5, "offset": 15}


def test_user_update_success_and_validation_error():
    service = AdminService()
    with build_client(service) as client:
        success = client.put("/api/admin/users/other", json={"full_name": "Updated"})
        invalid = client.put("/api/admin/users/other", json={"full_name": "invalid"})
    assert success.status_code == 200
    assert invalid.status_code == 422
    assert service.calls[0] == ("update", "other", "tenant-a")


def test_cross_tenant_update_and_deactivate_are_forbidden():
    service = AdminService()
    with build_client(service, tenant_id="tenant-b") as client:
        update = client.put("/api/admin/users/other", json={"full_name": "Updated"})
        deletion = client.delete("/api/admin/users/other")
    assert update.status_code == 403
    assert deletion.status_code == 403


def test_deactivation_returns_no_content():
    service = AdminService()
    with build_client(service) as client:
        response = client.delete("/api/admin/users/other")
    assert response.status_code == 204
    assert response.content == b""


def test_permission_rejection_short_circuits_service():
    service = AdminService()
    with build_client(service, authorized=False) as client:
        response = client.get("/api/admin/users/")
    assert response.status_code == 403
    assert service.calls == []


def test_invalid_filter_enums_are_rejected_before_service():
    service = AdminService()
    with build_client(service) as client:
        bad_role = client.get("/api/admin/users/", params={"role": "super_admin"})
        bad_status = client.get("/api/admin/users/", params={"status": "unknown"})
    assert bad_role.status_code == 422
    assert bad_status.status_code == 422
    assert service.calls == []


def test_invalid_user_roles_rejected_at_request_boundary():
    from ai_karen_engine.api_routes.admin.users import AdminUserCreateRequest, AdminUserUpdateRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdminUserCreateRequest(
            email="person@example.com", password="test-value", full_name="Person",
            tenant_id="tenant-a", roles=["super_admin"],
        )
    with pytest.raises(ValidationError):
        AdminUserUpdateRequest(roles=["super_admin"])


def test_openapi_exposes_canonical_filter_enums():
    from ai_karen_engine.services.auth.auth_service import UserRole, UserStatus
    assert UserRole.ADMIN.value == "admin"
    assert UserStatus.ACTIVE.value == "active"
    app = FastAPI()
    app.include_router(router, prefix="/api")
    schema = app.openapi()
    params = schema["paths"]["/api/admin/users/"]["get"]["parameters"]
    for name, definition in (("role", "UserRole"), ("status", "UserStatus")):
        param = next(item for item in params if item["name"] == name)
        assert definition in str(param["schema"])


@pytest.mark.parametrize("roles,status", [(["user"], 403), (["admin"], 403), (["super_admin"], 201)])
def test_legacy_tenant_creation_uses_shared_platform_guard_and_audit(monkeypatch, roles, status):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ai_karen_engine.api_routes.system import database
    from ai_karen_engine.auth import rbac_middleware
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.database.integration_manager import DatabaseIntegrationManager
    from ai_karen_engine.services.admin import admin_tenant_service

    calls = []
    audit = []

    class TenantManagerProbe:
        async def create_tenant(self, **kwargs):
            calls.append(kwargs)
            config = kwargs["config"]
            return SimpleNamespace(
                id="tenant-created", name=config.name, slug=config.slug,
                subscription_tier=config.subscription_tier,
                created_at=datetime.now(timezone.utc),
            )

    manager = DatabaseIntegrationManager()
    manager._initialized = True
    manager.tenant_manager = TenantManagerProbe()
    monkeypatch.setattr(admin_tenant_service, "get_audit_logger", lambda: SimpleNamespace(
        log_audit_event=audit.append,
    ))
    app = FastAPI()
    app.include_router(database.router)
    app.dependency_overrides[rbac_middleware.resolve_current_user] = lambda: UserData.from_dict({
        "user_id": "platform-operator", "tenant_id": "tenant-a", "roles": roles,
    })
    app.dependency_overrides[database.get_db_manager] = lambda: manager
    payload = {
        "name": "Tenant", "slug": "tenant", "admin_email": "new@example.test",
        "admin_password": "StrongPassword1!", "admin_full_name": "Tenant Admin",
    }
    with TestClient(app) as client:
        response = client.post("/tenants", json=payload)
    assert response.status_code == status
    assert payload["admin_password"] not in response.text
    if status == 201:
        assert len(calls) == len(audit) == 1
        assert calls[0]["admin_password"] == payload["admin_password"]
        assert calls[0]["admin_full_name"] == payload["admin_full_name"]
        assert calls[0]["admin_email"] == payload["admin_email"]
        assert audit[0].user_id == "platform-operator"
        assert audit[0].tenant_id == "tenant-created"
        assert payload["admin_password"] not in repr(audit[0])
    else:
        assert calls == audit == []


def test_legacy_tenant_creation_requires_explicit_credentials():
    from ai_karen_engine.api_routes.system.database import TenantCreateRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TenantCreateRequest(name="Tenant", slug="tenant", admin_email="new@example.test")


def test_legacy_tenant_creation_redacts_unexpected_error_even_in_dev(monkeypatch):
    from ai_karen_engine.api_routes.system import database
    from ai_karen_engine.auth import rbac_middleware
    from ai_karen_engine.auth.models import UserData

    class Manager:
        async def create_tenant(self, **kwargs):
            raise RuntimeError("private-database-detail " + kwargs["admin_password"])

    app = FastAPI()
    app.include_router(database.router)
    app.dependency_overrides[rbac_middleware.resolve_current_user] = lambda: UserData.from_dict({
        "user_id": "platform-operator", "tenant_id": "tenant-a", "roles": ["super_admin"],
    })
    app.dependency_overrides[database.get_db_manager] = lambda: Manager()
    monkeypatch.setattr(database, "DEV_MODE", True)
    with TestClient(app) as client:
        response = client.post("/tenants", json={
            "name": "Tenant", "slug": "tenant", "admin_email": "new@example.test",
            "admin_password": "StrongPassword1!", "admin_full_name": "Tenant Admin",
        })
    assert response.status_code == 500
    assert response.json() == {"detail": "Tenant creation failed"}
