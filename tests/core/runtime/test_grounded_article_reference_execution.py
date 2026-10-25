"""Executable synthesis-gate tests: scoped article access must precede model calls."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.services.database.repositories import repository_factory


class ArticleServiceDouble:
    def __init__(self, document):
        self.document = document
        self.calls = []

    async def read_for_chat(self, *, execution_context, article_id):
        self.calls.append((execution_context.user_id, execution_context.tenant_id, article_id))
        return self.document


class MeterDouble:
    def __init__(self):
        self.model_calls = 0

    async def consume_model_call(self):
        self.model_calls += 1
        return False


def request():
    return SimpleNamespace(
        context=SimpleNamespace(user_id="owner", tenant_id="tenant-a", correlation_id="test"),
    )


def retrieved(*, source="plugin", article_id="article-1"):
    return SimpleNamespace(
        success=True, source=source, source_id="intelligent-search",
        sources=[{
            "url": "https://example.org/article",
            "evidence_level": "fetched_page",
            "article_id": article_id,
            "content": "Untrusted inline fallback must not enter synthesis",
        }],
    )


@pytest.mark.asyncio
async def test_unauthorized_plugin_does_not_resolve_reference_or_call_model(monkeypatch):
    articles = ArticleServiceDouble("private document")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=[]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == []
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_missing_scoped_article_does_not_use_inline_fallback(monkeypatch):
    articles = ArticleServiceDouble(None)
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=["intelligent-search"]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == [("owner", "tenant-a", "article-1")]
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_authorized_scoped_document_reaches_model_budget_gate(monkeypatch):
    articles = ArticleServiceDouble("Scoped verified document")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=["intelligent-search"]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == [("owner", "tenant-a", "article-1")]
    assert meter.model_calls == 1
