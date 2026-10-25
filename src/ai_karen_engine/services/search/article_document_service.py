"""Governed article bytes using the existing canonical ArtifactStore authority.

This service does not crawl URLs, authorize requests, or choose storage backends.
The runtime supplies verified identities and already-extracted content. The API
must authenticate before invoking these operations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from ai_karen_engine.services.database.repositories.artifact_store import (
    ArtifactStore,
    ArtifactUploadRequest,
)


@dataclass(frozen=True)
class SavedSearchArticle:
    artifact_id: str
    sha256: str
    bytes_count: int


class SearchArticleService:
    """Store and retrieve source text with explicit tenant and owner scope."""

    def __init__(self, artifacts: ArtifactStore, max_document_bytes: int = 2_000_000):
        if max_document_bytes <= 0:
            raise ValueError("Article byte budget must be positive")
        self._artifacts = artifacts
        self._max_document_bytes = max_document_bytes

    @staticmethod
    def _identity(tenant_id: str, user_id: str) -> None:
        if not tenant_id or tenant_id == "default" or not user_id:
            raise PermissionError("Explicit tenant and user identity required")

    async def save(
        self, *, tenant_id: str, user_id: str, source_url: str, title: str,
        document: str,
    ) -> SavedSearchArticle:
        self._identity(tenant_id, user_id)
        parsed = urlsplit(source_url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ValueError("Article source URL must be an HTTP(S) URL")
        data = document.encode("utf-8")
        if not data or len(data) > self._max_document_bytes:
            raise ValueError("Article content is empty or exceeds size limit")
        digest = hashlib.sha256(data).hexdigest()
        result = await self._artifacts.upload(ArtifactUploadRequest(
            tenant_id=tenant_id, user_id=user_id,
            kind="search_article", filename=f"{digest[:24]}.txt",
            content_type="text/plain; charset=utf-8", data=data,
            metadata={"kind": "search_article", "source_url": source_url, "title": title, "sha256": digest},
        ))
        if not result.success or result.data is None:
            raise RuntimeError("Article persistence unavailable")
        return SavedSearchArticle(result.data.id, digest, len(data))

    async def read(self, *, tenant_id: str, user_id: str, article_id: str) -> str | None:
        self._identity(tenant_id, user_id)
        if not article_id:
            raise ValueError("Article identifier is required")
        metadata = await self._artifacts.get_metadata(article_id, tenant_id)
        if not metadata.success or metadata.data is None:
            return None
        artifact = metadata.data
        if artifact.kind != "search_article" or artifact.user_id != user_id:
            return None
        if artifact.deleted_at is not None or artifact.size_bytes > self._max_document_bytes:
            return None
        result = await self._artifacts.download(article_id, tenant_id)
        if not result.success or result.data is None:
            raise RuntimeError("Article storage unavailable")
        data = result.data.read(self._max_document_bytes + 1)
        if len(data) > self._max_document_bytes:
            raise RuntimeError("Article exceeds retrieval limit")
        if hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise RuntimeError("Article integrity verification failed")
        return data.decode("utf-8")

    async def read_for_chat(self, *, execution_context, article_id: str, source_url: str | None = None) -> str | None:
        """Resolve a browser-supplied research reference for canonical chat.

        The caller's authenticated runtime principal, not request metadata,
        is the authority for tenant and user scope. A reference does not grant
        access by itself. The underlying read enforces artifact ownership,
        deletion status, size and content integrity.
        """
        execution_context.require_authenticated_user()
        tenant_id = str(execution_context.tenant_id or "").strip()
        user_id = str(execution_context.user_id or "").strip()
        self._identity(tenant_id, user_id)
        if not isinstance(article_id, str) or not article_id or len(article_id) > 128:
            raise ValueError("Valid article identifier is required")
        # Reject missing citation provenance before touching document bytes.
        if not isinstance(source_url, str) or not source_url:
            return None
        content = await self.read(
            tenant_id=tenant_id, user_id=user_id, article_id=article_id,
        )
        if content is None:
            return None
        # The plugin-provided citation must match stored source provenance;
        # possession of a valid article ID cannot launder a different URL.
        source = await self._artifacts.get_metadata(article_id, tenant_id)
        if not source.success or source.data is None:
            return None
        artifact = source.data
        if (
            artifact.kind != "search_article"
            or artifact.user_id != user_id
            or artifact.deleted_at is not None
            or artifact.metadata.get("source_url") != source_url
        ):
            return None
        return content
