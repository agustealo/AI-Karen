from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextErrorType(str, Enum):
    """Compatibility error types for runtime file/context adapters."""

    INTEGRATION_ERROR = "integration_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class ContextError(Exception):
    """Runtime context adapter error wrapper."""

    message: str
    error_type: ContextErrorType
    context_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.message


class FileUploadStatus(str, Enum):
    """Status for runtime file uploads."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ContextFile:
    """Runtime file descriptor used by LangGraph-side file upload handling."""

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
class ContextData:
    """Container for legacy LangGraph context records and related files."""

    context_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    prompt: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    user_settings: Dict[str, Any] = field(default_factory=dict)
    memories: List[Dict[str, Any]] = field(default_factory=list)
    files: List[ContextFile] = field(default_factory=list)
    saved_contexts: List[Dict[str, Any]] = field(default_factory=list)
    file_context: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ContextResponse:
    """Compatibility response wrapper for runtime context lookups."""

    success: bool
    context_data: Optional[ContextData] = None
    error_message: Optional[str] = None


@dataclass
class ContextUpdateRequest:
    """Compatibility request wrapper for runtime context updates."""

    files: Optional[List[ContextFile]] = None
    saved_contexts: Optional[List[Dict[str, Any]]] = None
    file_context: Optional[List[Dict[str, Any]]] = None


class ContextManager:
    """Compatibility adapter over the canonical memory/context runtime.

    This class is not a context authority. It preserves LangGraph/file-upload
    callers until they consume Runtime-produced prompt context directly.
    """

    def __init__(self, memory_service: Optional[Any] = None):
        self.memory_service = memory_service
        self._context_store: Dict[str, ContextData] = {}

    async def build_context(
        self,
        *,
        user_id: str,
        tenant_id: Optional[str],
        session_id: Optional[str],
        prompt: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_settings: Optional[Dict[str, Any]] = None,
        memories: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "prompt": prompt,
            "conversation_history": conversation_history or [],
            "user_settings": user_settings or {},
            "memories": memories or [],
        }

        memory_service = self.memory_service
        if (
            memory_service is not None
            and tenant_id
            and hasattr(memory_service, "build_context")
        ):
            try:
                retrieved_context = await memory_service.build_context(
                    tenant_id=tenant_id,
                    query=prompt,
                    user_id=user_id,
                    session_id=session_id,
                    conversation_id=session_id,
                )
                if isinstance(retrieved_context, dict):
                    context.update(retrieved_context)
            except TypeError:
                logger.debug(
                    "Memory service build_context signature mismatch; using LangGraph compatibility context"
                )
            except Exception as exc:
                logger.warning("LangGraph context memory enrichment failed: %s", exc)
        elif memory_service is not None and not tenant_id:
            logger.warning("LangGraph memory enrichment skipped: missing tenant_id")

        return context

    def clear_context_cache(self) -> None:
        """Compatibility no-op for legacy orchestrator cleanup."""
        return None

    async def get_context(self, context_id: str, **_: Any) -> ContextResponse:
        if not context_id:
            return ContextResponse(success=False, error_message="context_id is required")

        context_data = self._context_store.get(context_id)
        if context_data is None:
            context_data = ContextData(context_id=context_id)
            self._context_store[context_id] = context_data
        return ContextResponse(success=True, context_data=context_data)

    async def update_context(
        self,
        context_id: str,
        request: Optional[ContextUpdateRequest] = None,
        **updates: Any,
    ) -> ContextResponse:
        if not context_id:
            return ContextResponse(success=False, error_message="context_id is required")

        context_data = self._context_store.get(context_id)
        if context_data is None:
            context_data = ContextData(context_id=context_id)
            self._context_store[context_id] = context_data

        payload = request or ContextUpdateRequest()
        if payload.files is not None:
            context_data.files = list(payload.files)
        if payload.saved_contexts is not None:
            context_data.saved_contexts = list(payload.saved_contexts)
        if payload.file_context is not None:
            context_data.file_context = list(payload.file_context)

        for key, value in updates.items():
            if hasattr(context_data, key):
                setattr(context_data, key, value)

        return ContextResponse(success=True, context_data=context_data)


__all__ = [
    "ContextData",
    "ContextError",
    "ContextErrorType",
    "ContextFile",
    "ContextManager",
    "ContextResponse",
    "ContextUpdateRequest",
    "FileUploadStatus",
]
