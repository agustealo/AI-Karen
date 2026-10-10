"""HTTP contract for tenant-scoped extension catalog reads."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from ai_karen_engine.api_routes.extensions import extensions as routes


@pytest.fixture
def catalog_app(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/extensions")
    requests = []

    class CatalogManager:
        async def refresh_extensions(self, *, user_context):
            requests.append(dict(user_context))
            return [{
                "id": "weather",
                "name": "weather",
                "version": "1.0",
                "status": "registered",
                "capabilities": {},
            }]

    monkeypatch.setattr(routes, "get_extension_manager", lambda: CatalogManager())
    return app, requests


@pytest.mark.asyncio
async def test_admin_catalog_get_returns_real_backend_discovery(catalog_app, monkeypatch):
    app, received = catalog_app

    async def admin(_request):
        return {
            "user_id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "roles": ["admin"],
        }

    monkeypatch.setattr(routes, "get_current_user", admin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/extensions/list")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["weather"]
    assert received[0]["tenant_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_unauthenticated_catalog_get_remains_unauthorized(catalog_app, monkeypatch):
    app, received = catalog_app

    async def guest(_request):
        return {"user_id": "guest", "authenticated": False}

    monkeypatch.setattr(routes, "get_current_user", guest)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/extensions/list")
    assert response.status_code == 401
    assert received == []


@pytest.mark.asyncio
async def test_catalog_get_rejects_missing_tenant(catalog_app, monkeypatch):
    app, received = catalog_app

    async def missing_tenant(_request):
        return {"user_id": "user", "roles": ["admin"]}

    monkeypatch.setattr(routes, "get_current_user", missing_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/extensions/list")
    assert response.status_code == 401
    assert received == []


@pytest.mark.asyncio
async def test_catalog_get_denies_unprivileged_role(catalog_app, monkeypatch):
    app, received = catalog_app

    async def unprivileged(_request):
        return {"user_id": "user", "tenant_id": "tenant-a", "roles": []}

    monkeypatch.setattr(routes, "get_current_user", unprivileged)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/extensions/list")
    assert response.status_code == 403
    assert response.json()["detail"] == "Extension catalog access denied"
    assert received == []



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,json_body",
    [
        ("POST", "/api/extensions/install", {"plugin_id": "time-query"}),
        ("POST", "/api/extensions/time-query/load", None),
        ("POST", "/api/extensions/time-query/unload", None),
        ("POST", "/api/extensions/time-query/remove-ui", None),
        ("GET", "/api/extensions/debug/system-status", None),
    ],
)
async def test_extension_lifecycle_requires_authentication(
    catalog_app, monkeypatch, method, path, json_body
):
    app, _ = catalog_app

    async def guest(_request):
        return {"user_id": "guest", "authenticated": False}

    monkeypatch.setattr(routes, "get_current_user", guest)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_extension_install_requires_plugin_management_permission(
    catalog_app, monkeypatch
):
    app, _ = catalog_app

    async def viewer(_request):
        return {
            "user_id": "user",
            "tenant_id": "tenant-a",
            "roles": [],
        }

    monkeypatch.setattr(routes, "get_current_user", viewer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/extensions/install", json={"plugin_id": "time-query"}
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "Plugin management access denied"



@pytest.mark.asyncio
async def test_load_extension_supports_canonical_dict_status(catalog_app, monkeypatch):
    app, _ = catalog_app

    async def admin(_request):
        return {
            "user_id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "roles": ["admin"],
        }

    class Manager:
        async def load_extension(self, name):
            assert name == "intelligent-search"
            return {"status": "enabled", "name": name}

        async def refresh_extensions(self):
            return []

    monkeypatch.setattr(routes, "get_current_user", admin)
    monkeypatch.setattr(routes, "get_extension_manager", lambda: Manager())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/extensions/intelligent-search/load")
    assert response.status_code == 200
    assert response.json()["status"] == "enabled"
