"""Runtime emits an article ID only after durable persistence succeeds."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


class SavedArticles:
    async def save(self, **kwargs):
        return SimpleNamespace(artifact_id="artifact-real-123")


class FailedArticles:
    async def save(self, **kwargs):
        raise RuntimeError("storage not configured")


@pytest.mark.asyncio
async def test_article_id_requires_successful_storage():
    service = InternetCapabilityService(article_service=SavedArticles())
    pages = [{"url": "https://example.org/story", "markdown": "Full article", "metadata": {"title": "Story"}}]
    await service._persist_article_documents(
        pages, SimpleNamespace(tenant_id="tenant-a", user_id="user-a", correlation_id="request-a")
    )
    assert pages[0]["article_id"] == "artifact-real-123"


@pytest.mark.asyncio
async def test_failed_storage_does_not_invent_document_id():
    service = InternetCapabilityService(article_service=FailedArticles())
    pages = [{"url": "https://example.org/story", "markdown": "Full article"}]
    await service._persist_article_documents(
        pages, SimpleNamespace(tenant_id="tenant-a", user_id="user-a", correlation_id="request-b")
    )
    assert "article_id" not in pages[0]


@pytest.mark.asyncio
async def test_anonymous_context_never_persists_article():
    service = InternetCapabilityService(article_service=SavedArticles())
    pages = [{"url": "https://example.org/story", "markdown": "Full article"}]
    await service._persist_article_documents(
        pages, SimpleNamespace(tenant_id="default", user_id="anonymous", correlation_id="request-c")
    )
    assert "article_id" not in pages[0]
