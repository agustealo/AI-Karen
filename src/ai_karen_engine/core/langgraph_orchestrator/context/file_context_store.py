from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ContextErrorType(str, Enum):
    INTEGRATION_ERROR = "integration_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class ContextError(Exception):
    message: str
    error_type: ContextErrorType
    context_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.message


class FileUploadStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ContextFile:
    file_id: str
    filename: str
    file_type: str
    file_size: int
    mime_type: str
    content_hash: str
    upload_status: FileUploadStatus
    upload_timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    storage_path: Optional[str] = None
    extracted_text: Optional[str] = None
    extracted_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "content_hash": self.content_hash,
            "upload_status": self.upload_status.value,
            "upload_timestamp": self.upload_timestamp.isoformat(),
            "metadata": self.metadata,
            "storage_path": self.storage_path,
            "extracted_text": self.extracted_text,
            "extracted_metadata": self.extracted_metadata,
        }


@dataclass
class FileContextData:
    context_id: Optional[str] = None
    files: List[ContextFile] = field(default_factory=list)
    saved_contexts: List[Dict[str, Any]] = field(default_factory=list)
    file_context: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FileContextResponse:
    success: bool
    context_data: Optional[FileContextData] = None
    error_message: Optional[str] = None


@dataclass
class FileContextUpdateRequest:
    files: Optional[List[ContextFile]] = None
    saved_contexts: Optional[List[Dict[str, Any]]] = None
    file_context: Optional[List[Dict[str, Any]]] = None


class FileContextStore:
    """Process-local compatibility store for LangGraph file-upload metadata only."""

    def __init__(self) -> None:
        self._contexts: Dict[str, FileContextData] = {}

    async def get_context(self, context_id: str) -> FileContextResponse:
        if not context_id:
            return FileContextResponse(success=False, error_message="context_id is required")
        data = self._contexts.setdefault(context_id, FileContextData(context_id=context_id))
        return FileContextResponse(success=True, context_data=data)

    async def update_context(
        self,
        context_id: str,
        request: Optional[FileContextUpdateRequest] = None,
    ) -> FileContextResponse:
        if not context_id:
            return FileContextResponse(success=False, error_message="context_id is required")
        data = self._contexts.setdefault(context_id, FileContextData(context_id=context_id))
        payload = request or FileContextUpdateRequest()
        if payload.files is not None:
            data.files = list(payload.files)
        if payload.saved_contexts is not None:
            data.saved_contexts = list(payload.saved_contexts)
        if payload.file_context is not None:
            data.file_context = list(payload.file_context)
        return FileContextResponse(success=True, context_data=data)


__all__ = [
    "ContextError",
    "ContextErrorType",
    "ContextFile",
    "FileContextData",
    "FileContextResponse",
    "FileContextStore",
    "FileContextUpdateRequest",
    "FileUploadStatus",
]
