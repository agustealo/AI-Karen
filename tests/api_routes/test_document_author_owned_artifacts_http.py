"""Owner-scoped, bounded artifact discovery used by author-consent UI."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from ai_karen_engine.api_routes import artifacts
from ai_karen_engine.services.database.repositories.artifact_store import Artifact
from ai_karen_engine.services.database.repositories.base import RepositoryResult

pytestmark = pytest.mark.asyncio


@pytest.fixture
def owner_page(monkeypatch):
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    app = FastAPI()
    app.include_router(artifacts.router, prefix="/api")
    app.dependency_overrides[artifacts.get_current_user] = lambda: SimpleNamespace(
        tenant_id=tenant_id, user_id=user_id,
    )
    entry = Artifact(
        id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
        filename="owner.txt", kind="attachment", mime_type="text/plain",
        size_bytes=12, sha256="a" * 64,
        created_at=datetime.now(timezone.utc),
    )
    store = SimpleNamespace(list_owner_artifacts_page=AsyncMock(
        return_value=RepositoryResult(
            success=True, data=[entry],
            metadata={"has_more": False, "next_cursor": None},
        ),
    ))
    monkeypatch.setattr(artifacts, "_get_artifact_store", lambda: store)
    return app, store, entry, tenant_id, user_id


async def test_owner_inventory_uses_scoped_store_and_returns_only_metadata(owner_page):
    app, store, entry, tenant_id, user_id = owner_page
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get("/api/artifacts/owner-page?limit=20")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == entry.id
    assert response.json()["has_more"] is False
    assert response.json()["next_cursor"] is None
    assert "storage_key" not in response.text
    assert "storage_uri" not in response.text
    store.list_owner_artifacts_page.assert_awaited_once_with(
        tenant_id, user_id, limit=20, cursor=None,
    )


async def test_owner_inventory_rejects_invalid_limit_and_cursor(owner_page):
    app, store, *_ = owner_page
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        for path in (
            "/api/artifacts/owner-page?limit=0",
            "/api/artifacts/owner-page?limit=101",
            "/api/artifacts/owner-page?cursor=",
            "/api/artifacts/owner-page?cursor=" + "a" * 769,
        ):
            response = await client.get(path)
            assert response.status_code == 422
    store.list_owner_artifacts_page.assert_not_awaited()


async def test_owner_inventory_fails_closed_on_foreign_row(owner_page):
    app, store, entry, *_ = owner_page
    entry.user_id = str(uuid.uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get("/api/artifacts/owner-page")
    assert response.status_code == 503
    assert "owner.txt" not in response.text


async def test_owner_inventory_denies_broken_pagination_metadata(owner_page):
    app, store, entry, *_ = owner_page
    store.list_owner_artifacts_page.return_value = RepositoryResult(
        success=True, data=[entry], metadata={"has_more": True},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get("/api/artifacts/owner-page")
    assert response.status_code == 503
    assert "owner.txt" not in response.text


@pytest.mark.parametrize(
    ("data_override", "metadata", "cursor"),
    [
        (None, {"has_more": False, "next_cursor": None}, None),
        ("not-a-page", {"has_more": False, "next_cursor": None}, None),
        ("original", {}, None),
        ("original", {"has_more": "false", "next_cursor": None}, None),
        ("original", {"has_more": True, "next_cursor": None}, None),
        ("original", {"has_more": True, "next_cursor": "x" * 769}, None),
        ("original", {"has_more": True, "next_cursor": "reused"}, "reused"),
        ("empty", {"has_more": True, "next_cursor": "cursor"}, None),
        ("original", {"has_more": False, "next_cursor": "unexpected"}, None),
    ],
)
async def test_owner_inventory_rejects_inconsistent_repository_page(
    owner_page, data_override, metadata, cursor,
):
    app, store, entry, *_ = owner_page
    data = [entry] if data_override == "original" else (
        [] if data_override == "empty" else data_override
    )
    store.list_owner_artifacts_page.return_value = RepositoryResult(
        success=True, data=data, metadata=metadata,
    )
    query = "/api/artifacts/owner-page?limit=1"
    if cursor is not None:
        query += "&cursor=" + cursor
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get(query)
    assert response.status_code == 503
    assert "owner.txt" not in response.text


async def test_owner_inventory_rejects_more_rows_than_requested(owner_page):
    app, store, entry, *_ = owner_page
    store.list_owner_artifacts_page.return_value = RepositoryResult(
        success=True, data=[entry, entry],
        metadata={"has_more": False, "next_cursor": None},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.get("/api/artifacts/owner-page?limit=1")
    assert response.status_code == 503
    assert "owner.txt" not in response.text
