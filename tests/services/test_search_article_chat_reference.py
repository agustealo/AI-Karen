"""Research article references cannot override runtime-authenticated identity."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.search.article_document_service import SearchArticleService


class ScopedArticles(SearchArticleService):
    def __init__(self):
        self.calls = []

    async def read(self, **kwargs):
        self.calls.append(kwargs)
        return "tenant scoped content"


class RuntimeContext:
    def __init__(self, tenant_id="tenant-A", user_id="owner", allowed=True):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.allowed = allowed
        self.checked = False

    def require_authenticated_user(self):
        self.checked = True
        if not self.allowed:
            raise PermissionError("authenticated_principal_required")
        return SimpleNamespace(user_id=self.user_id, tenant_id=self.tenant_id)


@pytest.mark.asyncio
async def test_chat_reference_uses_principal_scope_not_reference_scope():
    service = ScopedArticles()
    context = RuntimeContext()
    result = await service.read_for_chat(execution_context=context, article_id="article-123")
    assert context.checked is True
    assert result == "tenant scoped content"
    assert service.calls == [{"tenant_id": "tenant-A", "user_id": "owner", "article_id": "article-123"}]


@pytest.mark.asyncio
async def test_unauthenticated_reference_never_reads_storage():
    service = ScopedArticles()
    with pytest.raises(PermissionError):
        await service.read_for_chat(execution_context=RuntimeContext(allowed=False), article_id="article-123")
    assert service.calls == []


@pytest.mark.asyncio
async def test_missing_tenant_never_reads_storage():
    service = ScopedArticles()
    with pytest.raises(PermissionError):
        await service.read_for_chat(execution_context=RuntimeContext(tenant_id=""), article_id="article-123")
    assert service.calls == []


@pytest.mark.asyncio
async def test_invalid_reference_never_reads_storage():
    service = ScopedArticles()
    with pytest.raises(ValueError):
        await service.read_for_chat(execution_context=RuntimeContext(), article_id="x" * 129)
    assert service.calls == []
