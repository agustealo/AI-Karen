"""Authenticated article detail route behavior, including identity isolation."""

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.plugins import plugins


@pytest.mark.asyncio
async def test_article_detail_returns_scoped_document(monkeypatch):
    calls = []

    class Articles:
        async def read(self, **kwargs):
            calls.append(kwargs)
            return "complete article"

    monkeypatch.setattr(
        "ai_karen_engine.services.database.repositories.repository_factory.get_runtime_search_article_service",
        lambda: Articles(),
    )
    result = await plugins.get_search_article(
        "article-123", {"user_id": "owner", "tenant_id": "tenant-A"}
    )
    assert result == {"article_id": "article-123", "full_content": "complete article"}
    assert calls == [
        {"tenant_id": "tenant-A", "user_id": "owner", "article_id": "article-123"}
    ]


@pytest.mark.asyncio
async def test_article_detail_masks_cross_owner_and_missing_documents(monkeypatch):
    class Articles:
        async def read(self, **kwargs):
            return None

    monkeypatch.setattr(
        "ai_karen_engine.services.database.repositories.repository_factory.get_runtime_search_article_service",
        lambda: Articles(),
    )
    with pytest.raises(HTTPException) as failure:
        await plugins.get_search_article(
            "article-123", {"user_id": "other", "tenant_id": "tenant-B"}
        )
    assert failure.value.status_code == 404


@pytest.mark.asyncio
async def test_article_detail_rejects_missing_scope_before_storage(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ai_karen_engine.services.database.repositories.repository_factory.get_runtime_search_article_service",
        lambda: calls.append("resolved"),
    )
    with pytest.raises(HTTPException) as failure:
        await plugins.get_search_article("article-123", {"user_id": "owner"})
    assert failure.value.status_code == 401
    assert not calls


@pytest.mark.asyncio
async def test_article_detail_reports_missing_storage(monkeypatch):
    monkeypatch.setattr(
        "ai_karen_engine.services.database.repositories.repository_factory.get_runtime_search_article_service",
        lambda: None,
    )
    with pytest.raises(HTTPException) as failure:
        await plugins.get_search_article(
            "article-123", {"user_id": "owner", "tenant_id": "tenant-A"}
        )
    assert failure.value.status_code == 503
