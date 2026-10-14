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
