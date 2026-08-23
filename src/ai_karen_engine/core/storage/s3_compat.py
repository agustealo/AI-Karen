"""S3 compatibility boundary.

Preserve portability across Supabase Storage, MinIO, S3-compatible local backend, AWS S3.
Artifact domain should not depend on Supabase-specific API semantics.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class StoredObject:
    key: str
    bucket: str
    size: int
    content_type: str
    last_modified: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


class ObjectStorageClient(ABC):
    """Generic object-storage operations contract."""

    @abstractmethod
    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def get(self, bucket: str, key: str) -> Optional[bytes]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def signed_get(self, bucket: str, key: str, expires_in_seconds: int = 600) -> str:
        raise NotImplementedError

    @abstractmethod
    async def signed_put(self, bucket: str, key: str, expires_in_seconds: int = 600) -> str:
        raise NotImplementedError

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def metadata(self, bucket: str, key: str) -> Optional[StoredObject]:
        raise NotImplementedError
