"""Article persistence must never cross tenant or owner boundaries."""

import hashlib
import io
from dataclasses import replace

import pytest

from ai_karen_engine.services.database.repositories.artifact_store import Artifact
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.search.article_document_service import SearchArticleService


class ArtifactDouble:
    def __init__(self):
        self.items = {}

    async def upload(self, request):
        data = request.data
        artifact = Artifact(
            id=str(len(self.items) + 1), tenant_id=request.tenant_id,
            user_id=request.user_id, kind=request.metadata["kind"],
            mime_type=request.content_type, size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            metadata=request.metadata,
        )
        self.items[artifact.id] = (artifact, data)
        return RepositoryResult(success=True, data=artifact)

    async def get_metadata(self, article_id, tenant_id):
        item = self.items.get(article_id)
        return RepositoryResult(
            success=True,
            data=item[0] if item and item[0].tenant_id == tenant_id else None,
        )

    async def download(self, article_id, tenant_id):
        item = self.items.get(article_id)
        return RepositoryResult(
            success=bool(item and item[0].tenant_id == tenant_id),
            data=io.BytesIO(item[1]) if item and item[0].tenant_id == tenant_id else None,
        )


@pytest.mark.asyncio
async def test_article_round_trip_and_source_metadata():
    store = ArtifactDouble()
    service = SearchArticleService(store)
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/history", title="History",
        document="Section one\\n\\nSection two",
    )
    assert saved.bytes_count > 0
    assert store.items[saved.artifact_id][0].metadata["kind"] == "search_article"
    assert await service.read(tenant_id="tenant-a", user_id="user-a", article_id=saved.artifact_id) == "Section one\\n\\nSection two"


@pytest.mark.asyncio
async def test_article_denies_cross_tenant_cross_user_and_other_artifact_type():
    store = ArtifactDouble()
    service = SearchArticleService(store)
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/article", title="Article", document="Private document",
    )
    assert await service.read(tenant_id="tenant-b", user_id="user-a", article_id=saved.artifact_id) is None
    assert await service.read(tenant_id="tenant-a", user_id="user-b", article_id=saved.artifact_id) is None
    item, body = store.items[saved.artifact_id]
    store.items[saved.artifact_id] = (replace(item, kind="attachment"), body)
    assert await service.read(tenant_id="tenant-a", user_id="user-a", article_id=saved.artifact_id) is None


@pytest.mark.asyncio
async def test_article_detects_tampered_content_and_rejects_missing_identity():
    store = ArtifactDouble()
    service = SearchArticleService(store)
    with pytest.raises(PermissionError):
        await service.save(
            tenant_id="default", user_id="user",
            source_url="https://example.org", title="x", document="a",
        )
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/article", title="Article", document="Original content",
    )
    artifact, _ = store.items[saved.artifact_id]
    store.items[saved.artifact_id] = (artifact, b"Tampered content")
    with pytest.raises(RuntimeError, match="integrity"):
        await service.read(tenant_id="tenant-a", user_id="user-a", article_id=saved.artifact_id)


@pytest.mark.asyncio
async def test_chat_reference_read_enforces_actual_artifact_owner_and_tenant():
    from types import SimpleNamespace

    store = ArtifactDouble()
    service = SearchArticleService(store)
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/research", title="Research",
        document="Private source content",
    )

    class Context:
        def __init__(self, tenant_id, user_id):
            self.tenant_id = tenant_id
            self.user_id = user_id

        def require_authenticated_user(self):
            return SimpleNamespace(user_id=self.user_id, tenant_id=self.tenant_id)

    assert await service.read_for_chat(
        execution_context=Context("tenant-a", "user-a"),
        article_id=saved.artifact_id,
    ) == "Private source content"
    assert await service.read_for_chat(
        execution_context=Context("tenant-a", "user-b"),
        article_id=saved.artifact_id,
    ) is None
    assert await service.read_for_chat(
        execution_context=Context("tenant-b", "user-a"),
        article_id=saved.artifact_id,
    ) is None


@pytest.mark.asyncio
async def test_chat_reference_rejects_misattributed_saved_source_url():
    from types import SimpleNamespace

    store = ArtifactDouble()
    service = SearchArticleService(store)
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/original", title="Original",
        document="Scoped trusted evidence",
    )

    class Context:
        tenant_id = "tenant-a"
        user_id = "user-a"

        def require_authenticated_user(self):
            return SimpleNamespace(tenant_id=self.tenant_id, user_id=self.user_id)

    context = Context()
    assert await service.read_for_chat(
        execution_context=context, article_id=saved.artifact_id,
        source_url="https://example.org/original",
    ) == "Scoped trusted evidence"
    assert await service.read_for_chat(
        execution_context=context, article_id=saved.artifact_id,
        source_url="https://example.org/forged-citation",
    ) is None


@pytest.mark.asyncio
async def test_chat_reference_requires_source_url_and_rejects_deleted_or_tampered_article():
    from types import SimpleNamespace

    store = ArtifactDouble()
    service = SearchArticleService(store)
    saved = await service.save(
        tenant_id="tenant-a", user_id="user-a",
        source_url="https://example.org/provenance", title="Provenance",
        document="Verified saved text",
    )

    class Context:
        tenant_id = "tenant-a"
        user_id = "user-a"

        def require_authenticated_user(self):
            return SimpleNamespace(tenant_id=self.tenant_id, user_id=self.user_id)

    context = Context()
    assert await service.read_for_chat(
        execution_context=context, article_id=saved.artifact_id,
    ) is None
    assert await service.read_for_chat(
        execution_context=context, article_id=saved.artifact_id,
        source_url="",
    ) is None

    artifact, document = store.items[saved.artifact_id]
    store.items[saved.artifact_id] = (replace(artifact, deleted_at=__import__("datetime").datetime.utcnow()), document)
    assert await service.read_for_chat(
        execution_context=context, article_id=saved.artifact_id,
        source_url="https://example.org/provenance",
    ) is None
    store.items[saved.artifact_id] = (artifact, b"tampered body")
    with pytest.raises(RuntimeError, match="integrity"):
        await service.read_for_chat(
            execution_context=context, article_id=saved.artifact_id,
            source_url="https://example.org/provenance",
        )
