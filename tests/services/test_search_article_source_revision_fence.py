"""Source-revision fencing for governed saved research citations.

An authorized source read must not return bytes from one revision after the
source record has changed or been revoked during retrieval.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ai_karen_engine.services.database.repositories.artifact_store import Artifact
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.search.article_document_service import SearchArticleService


SOURCE_URL = "https://example.org/approved-guide"
BODY = b"Verified company source text"


class RevisionChangingArtifactStore:
    """Model a source record that can change between metadata checks."""

    def __init__(self, *, latest: Artifact | None = None) -> None:
        self.initial = Artifact(
            id="source-1",
            tenant_id="tenant-a",
            user_id="owner-a",
            kind="search_article",
            size_bytes=len(BODY),
            sha256=hashlib.sha256(BODY).hexdigest(),
            metadata={"source_url": SOURCE_URL},
        )
        self.latest = latest
        self.metadata_calls = 0
        self.download_calls = 0

    async def get_metadata(self, artifact_id: str, tenant_id: str):
        self.metadata_calls += 1
        if artifact_id != self.initial.id or tenant_id != self.initial.tenant_id:
            return RepositoryResult(success=True, data=None)
        artifact = self.initial if self.metadata_calls == 1 else self.latest or self.initial
        return RepositoryResult(success=True, data=artifact)

    async def download(self, artifact_id: str, tenant_id: str):
        self.download_calls += 1
        assert artifact_id == self.initial.id
        assert tenant_id == self.initial.tenant_id
        return RepositoryResult(success=True, data=io.BytesIO(BODY))


class AuthenticatedContext:
    tenant_id = "tenant-a"
    user_id = "owner-a"

    def require_authenticated_user(self):
        return SimpleNamespace(tenant_id=self.tenant_id, user_id=self.user_id)


async def _read(store: RevisionChangingArtifactStore, source_url: str = SOURCE_URL):
    return await SearchArticleService(store).read_for_chat(
        execution_context=AuthenticatedContext(),
        article_id="source-1",
        source_url=source_url,
    )


@pytest.mark.asyncio
async def test_same_source_revision_is_retrievable():
    store = RevisionChangingArtifactStore()
    assert await _read(store) == BODY.decode("utf-8")
    assert store.metadata_calls == 2
    assert store.download_calls == 1


@pytest.mark.asyncio
async def test_concurrent_content_revision_invalidates_older_bytes():
    store = RevisionChangingArtifactStore()
    store.latest = replace(
        store.initial,
        sha256=hashlib.sha256(b"Other approved revision").hexdigest(),
    )
    assert await _read(store) is None


@pytest.mark.asyncio
async def test_concurrent_length_revision_invalidates_older_bytes():
    store = RevisionChangingArtifactStore()
    store.latest = replace(store.initial, size_bytes=len(BODY) + 1)
    assert await _read(store) is None


@pytest.mark.asyncio
async def test_concurrent_deletion_invalidates_older_bytes():
    store = RevisionChangingArtifactStore()
    store.latest = replace(
        store.initial, deleted_at=datetime.now(timezone.utc)
    )
    assert await _read(store) is None


@pytest.mark.asyncio
async def test_concurrent_owner_or_tenant_change_invalidates_older_bytes():
    for changes in ({"user_id": "owner-b"}, {"tenant_id": "tenant-b"}):
        store = RevisionChangingArtifactStore()
        store.latest = replace(store.initial, **changes)
        assert await _read(store) is None


@pytest.mark.asyncio
async def test_concurrent_source_provenance_change_invalidates_older_bytes():
    store = RevisionChangingArtifactStore()
    store.latest = replace(
        store.initial, metadata={"source_url": "https://example.org/other"}
    )
    assert await _read(store) is None


@pytest.mark.asyncio
async def test_cross_tenant_reference_is_rejected_before_download():
    store = RevisionChangingArtifactStore()

    class OtherTenant(AuthenticatedContext):
        tenant_id = "tenant-b"

    assert await SearchArticleService(store).read_for_chat(
        execution_context=OtherTenant(),
        article_id="source-1",
        source_url=SOURCE_URL,
    ) is None
    assert store.download_calls == 0


@pytest.mark.asyncio
async def test_citation_url_must_match_latest_metadata():
    store = RevisionChangingArtifactStore()
    assert await _read(store, "https://example.org/forged") is None
