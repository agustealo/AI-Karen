"""Resumable upload foundation.

TUS-style resumable uploads for larger artifacts.
Requirements: progress, resume, retry, cancel, network recovery, upload ID persistence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from ai_karen_engine.core.storage.client import UploadIntent, UploadProgress, UploadStatus


class TusError(str, Enum):
    NETWORK_ERROR = "network_error"
    INVALID_OFFSET = "invalid_offset"
    UPLOAD_EXPIRED = "upload_expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TusSession:
    upload_id: uuid.UUID
    intent: UploadIntent
    offset: int = 0
    status: UploadStatus = UploadStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TusResult:
    upload_id: uuid.UUID
    final_path: str
    bytes_written: int
    completed: bool = False


class ResumableUploadManager:
    """Manages resumable upload sessions.

    Backend implementation will persist sessions.
    Frontend implementation will keep upload ID for current session.
    """

    def __init__(self) -> None:
        self._sessions: Dict[uuid.UUID, TusSession] = {}

    def create_session(self, intent: UploadIntent) -> TusSession:
        session = TusSession(upload_id=intent.upload_id, intent=intent)
        self._sessions[session.upload_id] = session
        return session

    def get_session(self, upload_id: uuid.UUID) -> Optional[TusSession]:
        return self._sessions.get(upload_id)

    def update_offset(self, upload_id: uuid.UUID, offset: int) -> bool:
        session = self._sessions.get(upload_id)
        if not session:
            return False
        object.__setattr__(session, "offset", offset)
        return True

    def complete(self, upload_id: uuid.UUID, final_path: str) -> Optional[TusResult]:
        session = self._sessions.get(upload_id)
        if not session:
            return None
        result = TusResult(upload_id=upload_id, final_path=final_path, bytes_written=session.offset, completed=True)
        return result

    def cancel(self, upload_id: uuid.UUID) -> bool:
        session = self._sessions.pop(upload_id, None)
        if session:
            object.__setattr__(session, "status", UploadStatus.CANCELLED)
            return True
        return False
