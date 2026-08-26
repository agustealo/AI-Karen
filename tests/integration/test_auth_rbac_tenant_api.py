from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.auth import auth as auth_routes
from ai_karen_engine.auth.session import get_current_user as get_authenticated_user


pytestmark = pytest.mark.asyncio


@dataclass
class _CreatedUser:
    id: str = "created-user"
    email: str = "created@example.test"
    full_name: str = "Created User"
    roles: list[str] = None
    tenant_id: str = "tenant-a"
    preferences: dict[str, Any] = None
    created_at: datetime = datetime(2026, 1, 1)
    last_login: None = None

    def __post_init__(self) -> None:
        self.roles = self.roles or ["user"]
        self.preferences = self.preferences or {}
        self.status = type("Status", (), {"value": "active"})()


class _AuthServiceProbe:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.stats_calls: list[str | None] = []
        self.password_calls: list[tuple[str, str, str]] = []

    async def create_user(self, **kwargs: Any):
        self.create_calls.append(kwargs)
        user = _CreatedUser(
            email=kwargs["email"],
            full_name=kwargs["full_name"],
            roles=list(kwargs.get("roles") or ["user"]),
            tenant_id=kwargs["tenant_id"],
        )
        return user, None

    async def get_auth_stats(self, tenant_id: str | None = None) -> dict[str, Any]:
        self.stats_calls.append(tenant_id)
        return {"total_users": 1, "tenant_id": tenant_id}

    async def change_user_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> None:
        self.password_calls.append((user_id, current_password, new_password))
        return None


async def _request(
    principal: dict[str, Any],
    service: _AuthServiceProbe,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
):
    app = FastAPI()
    app.include_router(auth_routes.router)

    async def current_user_override() -> dict[str, Any]:
        return principal

    async def auth_service_override() -> _AuthServiceProbe:
        return service

    app.dependency_overrides[get_authenticated_user] = current_user_override
    app.dependency_overrides[auth_routes.get_auth_service] = auth_service_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json)


def _principal(*, roles: list[str], tenant_id: str | None = "tenant-a") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": "principal-user",
        "email": "principal@example.test",
        "roles": roles,
        "authenticated": True,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return payload


async def test_regular_user_is_denied_admin_user_creation_before_service_execution() -> None:
    service = _AuthServiceProbe()
    response = await _request(
        _principal(roles=["user"]),
        service,
        "POST",
        "/auth/create-user",
        json={
            "email": "created@example.test",
            "password": "StrongPassword1!",
            "full_name": "Created User",
            "roles": ["user"],
        },
    )

    assert response.status_code == 403
    assert service.create_calls == []


async def test_tenant_admin_user_creation_is_forced_into_authenticated_tenant() -> None:
    service = _AuthServiceProbe()
    response = await _request(
        _principal(roles=["admin"], tenant_id="tenant-a"),
        service,
        "POST",
        "/auth/create-user",
        json={
            "email": "created@example.test",
            "password": "StrongPassword1!",
            "full_name": "Created User",
            "roles": ["user"],
        },
    )

    assert response.status_code == 201
    assert len(service.create_calls) == 1
    assert service.create_calls[0]["tenant_id"] == "tenant-a"


async def test_tenant_admin_without_explicit_tenant_scope_is_denied() -> None:
    service = _AuthServiceProbe()
    response = await _request(
        _principal(roles=["admin"], tenant_id=None),
        service,
        "POST",
        "/auth/create-user",
        json={
            "email": "created@example.test",
            "password": "StrongPassword1!",
            "full_name": "Created User",
            "roles": ["user"],
        },
    )

    assert response.status_code == 403
    assert service.create_calls == []


async def test_tenant_admin_stats_are_scoped_but_super_admin_stats_are_global() -> None:
    tenant_service = _AuthServiceProbe()
    tenant_response = await _request(
        _principal(roles=["admin"], tenant_id="tenant-a"),
        tenant_service,
        "GET",
        "/auth/stats",
    )
    assert tenant_response.status_code == 200
    assert tenant_service.stats_calls == ["tenant-a"]

    global_service = _AuthServiceProbe()
    global_response = await _request(
        _principal(roles=["super_admin"], tenant_id=None),
        global_service,
        "GET",
        "/auth/stats",
    )
    assert global_response.status_code == 200
    assert global_service.stats_calls == [None]


async def test_password_change_cannot_target_a_different_user() -> None:
    service = _AuthServiceProbe()
    response = await _request(
        _principal(roles=["user"], tenant_id="tenant-a"),
        service,
        "POST",
        "/auth/change-password",
        json={
            "current_password": "Original1!",
            "new_password": "Replacement2!",
            "confirm_password": "Replacement2!",
            "user_id": "victim-user",
        },
    )

    assert response.status_code == 200
    assert service.password_calls == [
        ("principal-user", "Original1!", "Replacement2!")
    ]
