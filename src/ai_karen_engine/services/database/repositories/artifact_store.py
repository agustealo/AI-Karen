"""Artifact store contract for KAREN's durable file/object layer."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, BinaryIO

from .base import Repository, RepositoryResult


@dataclass
class Artifact:
    """Canonical artifact representation."""

    id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    kind: str = "attachment"
    mime_type: str = "application/octet-stream"
    filename: str = ""
    size_bytes: int = 0
    sha256: str = ""
    storage_key: str = ""
    storage_backend: str = "supabase"
    created_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactUploadRequest:
    """Request to upload an artifact."""

    tenant_id: str
    user_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    kind: str = "attachment"
    filename: str = ""
    content_type: str = "application/octet-stream"
    data: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerifiedArtifactText:
    """Inert, digest-verified text from one active artifact owned by a principal."""

    artifact_id: str
    tenant_id: str
    user_id: str
    filename: str
    mime_type: str
    sha256: str
    text: str


class ArtifactStore(Repository):
    """Canonical contract for durable artifact/object storage.

    Implementations may use Supabase Storage, local filesystem, or
    any backend.  Application code never talks to the backend
    directly.
    """

    @abstractmethod
    async def upload(self, request: ArtifactUploadRequest) -> RepositoryResult[Artifact]:
        """Store an artifact and return its metadata."""

    @abstractmethod
    async def download(self, artifact_id: str, tenant_id: str) -> RepositoryResult[BinaryIO]:
        """Retrieve artifact bytes."""

    @abstractmethod
    async def read_owner_active_code(
        self, artifact_id: str, tenant_id: str, user_id: str
    ) -> RepositoryResult[VerifiedArtifactText]:
        """Read small inert source text with owner, active state and digest proven.

        Only caller-authenticated tenant/user IDs may be passed. The repository
        must enforce these IDs in its read query, not rely on UI authorization.
        Failure must never return source bytes or other tenants' metadata.
        """

    @abstractmethod
    async def get_metadata(self, artifact_id: str, tenant_id: str) -> RepositoryResult[Optional[Artifact]]:
        """Retrieve artifact metadata without downloading bytes."""

    @abstractmethod
    async def list_artifacts(
        self, tenant_id: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None
    ) -> RepositoryResult[Sequence[Artifact]]:
        """List artifacts filtered by tenant and optional scope."""

    @abstractmethod
    async def list_owner_artifacts_page(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> RepositoryResult[Sequence[Artifact]]:
        """List only one authenticated owner's active metadata using keyset paging.

        The result's metadata carries has_more: bool and next_cursor: str | None.
        Cursors select a position, never confer access. No bytes or storage
        locations are exposed by the explorer projection.
        """

    @abstractmethod
    async def delete(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Delete an artifact (metadata + bytes)."""

    @abstractmethod
    async def archive(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Soft-delete an artifact (retain metadata + bytes)."""

    @abstractmethod
    async def restore(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Restore an archived artifact."""

    @abstractmethod
    async def list_archived(
        self, tenant_id: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None
    ) -> RepositoryResult[Sequence[Artifact]]:
        """List archived artifacts filtered by tenant and optional scope."""

    @abstractmethod
    async def purge(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Permanently delete an archived artifact."""
