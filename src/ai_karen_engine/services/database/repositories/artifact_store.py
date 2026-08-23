"""Artifact store contract for KAREN's durable file/object layer."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, BinaryIO

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
    async def get_metadata(self, artifact_id: str, tenant_id: str) -> RepositoryResult[Optional[Artifact]]:
        """Retrieve artifact metadata without downloading bytes."""

    @abstractmethod
    async def list_artifacts(
        self, tenant_id: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None
    ) -> RepositoryResult[Sequence[Artifact]]:
        """List artifacts filtered by tenant and optional scope."""

    @abstractmethod
    async def delete(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        """Delete an artifact (metadata + bytes)."""
