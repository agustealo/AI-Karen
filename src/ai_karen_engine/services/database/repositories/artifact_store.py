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
    folder_id: Optional[str] = None
    organization_revision: Optional[int] = None


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


@dataclass(frozen=True, slots=True)
class ArtifactFolder:
    """Owner-scoped logical organization metadata; never a content grant."""

    folder_id: str
    parent_folder_id: Optional[str]
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime


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

    async def read_owner_active_text_bounded(
        self, artifact_id: str, tenant_id: str, user_id: str, *,
        max_bytes: int = 65536,
    ) -> RepositoryResult[VerifiedArtifactText]:
        """Read current owner-authenticated inert UTF-8 text without buffering.

        Implementations must enforce max_bytes during object transfer, before
        storage bytes are materialized, while also verifying the live canonical
        owner, active state, expected digest and actual digest. This base method
        explicitly denies until the storage backend proves that capability.
        Neither download() nor read_owner_active_code() satisfies the bound.
        """
        return RepositoryResult(
            success=False, error="bounded_artifact_read_unavailable"
        )

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
        folder_scoped: bool = False,
        folder_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> RepositoryResult[Sequence[Artifact]]:
        """List only one authenticated owner's active metadata using keyset paging.

        The result's metadata carries has_more: bool and next_cursor: str | None.
        Search is a bounded literal case-insensitive filename substring.
        folder_scoped=False preserves flat inventory; True selects root (None)
        or one folder. Cursors select a position, never confer access. No bytes or storage
        locations are exposed by the explorer projection.
        """

    async def owner_hierarchy_available(
        self, tenant_id: str, user_id: str,
    ) -> RepositoryResult[bool]:
        """Probe live backend capability, never an actor authorization grant."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def owner_folder_deletion_available(
        self, tenant_id: str, user_id: str,
    ) -> RepositoryResult[bool]:
        """Probe empty-folder deletion support without mutating metadata."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def list_owner_folders(
        self, tenant_id: str, user_id: str, *,
        parent_folder_id: Optional[str] = None,
        after_folder_id: Optional[str] = None,
        limit: int = 100,
    ) -> RepositoryResult[Sequence[ArtifactFolder]]:
        """Bounded metadata only. Caller supplies authenticated actor identity."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def create_owner_folder(
        self, tenant_id: str, user_id: str, *, name: str,
        parent_folder_id: Optional[str] = None,
    ) -> RepositoryResult[ArtifactFolder]:
        """Create logical metadata for the authenticated owner."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def rename_owner_folder(
        self, tenant_id: str, user_id: str, folder_id: str, *,
        name: str, expected_revision: int,
    ) -> RepositoryResult[ArtifactFolder]:
        """Rename with an expected revision, without changing identity."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def resolve_owner_breadcrumbs(
        self, tenant_id: str, user_id: str, folder_id: str,
    ) -> RepositoryResult[Sequence[ArtifactFolder]]:
        """Return complete bounded root-to-folder ancestry, or fail closed."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def move_owner_folder(
        self, tenant_id: str, user_id: str, folder_id: str, *,
        parent_folder_id: Optional[str], expected_revision: int,
    ) -> RepositoryResult[int]:
        """Compare-and-swap movement; success returns committed revision."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def move_owner_artifact(
        self, tenant_id: str, user_id: str, artifact_id: str, *,
        folder_id: Optional[str], expected_revision: int,
    ) -> RepositoryResult[int]:
        """Move active metadata only; return the committed organization revision."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    async def delete_empty_owner_folder(
        self, tenant_id: str, user_id: str, folder_id: str, *,
        expected_revision: int,
    ) -> RepositoryResult[bool]:
        """Delete only empty folder metadata; never detach or delete artifacts."""
        return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

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
