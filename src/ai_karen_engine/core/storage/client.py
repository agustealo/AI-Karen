"""Storage upload client abstraction.

Frontend/service contract for direct Storage uploads.
Does not depend on Supabase-specific API semantics.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class UploadStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class UploadIntent:
    upload_id: uuid.UUID = field(default_factory=uuid.uuid4)
    bucket: str = ""
    path: str = ""
    content_type: str = "application/octet-stream"
    content_length: int = 0
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    expires_at: Optional[datetime] = None


@dataclass(frozen=True)
class UploadProgress:
    bytes_sent: int = 0
    total_bytes: int = 0
    percent: float = 0.0


class ArtifactUploadClient(ABC):
    """Abstract upload client contract."""

    @abstractmethod
    async def request_intent(self, bucket: str, path: str, content_type: str, content_length: int) -> UploadIntent:
        raise NotImplementedError

    @abstractmethod
    async def upload_small(self, intent: UploadIntent, data: bytes) -> str:
        raise NotImplementedError

    @abstractmethod
    async def upload_resumable(self, intent: UploadIntent) -> "ResumableUpload":
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, upload_id: uuid.UUID) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class ResumableUpload:
    upload_id: uuid.UUID
    intent: UploadIntent
    status: UploadStatus = UploadStatus.PENDING
    progress: UploadProgress = field(default_factory=UploadProgress)
    error: Optional[str] = None

    async def start(self) -> None:
        raise NotImplementedError

    async def pause(self) -> None:
        raise NotImplementedError

    async def resume(self) -> None:
        raise NotImplementedError

    async def cancel(self) -> None:
        raise NotImplementedError

    def progress_callback(self, handler: Any) -> None:
        raise NotImplementedError
