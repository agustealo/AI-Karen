"""
File Upload Handler for Context Management

Handles multi-format file uploads with preprocessing, validation,
security scanning, storage management, and optional database persistence.
"""

import hashlib
import json
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from ai_karen_engine.context_management.models import (
    ContextFile,
    ContextFileType,
    ContextStatus,
)

logger = logging.getLogger(__name__)


class FileUploadHandler:
    """
    Comprehensive file upload handler with support for multiple file types,
    validation, security scanning, and preprocessing.
    """

    DEFAULT_MAX_FILENAME_LENGTH = 180

    def __init__(
        self,
        storage_path: str = "/tmp/context_files",
        max_file_size_mb: int = 100,
        allowed_extensions: Optional[List[str]] = None,
        scan_for_malware: bool = True,
        extract_text: bool = True,
        db_client: Optional[Any] = None,
        allow_open_access_without_db: bool = False,
    ):
        """
        Initialize file upload handler.

        Args:
            storage_path: Base path for file storage
            max_file_size_mb: Maximum file size in MB
            allowed_extensions: List of allowed file extensions
            scan_for_malware: Whether to scan for malware
            extract_text: Whether to extract text content
            db_client: Optional DB client for persistence
            allow_open_access_without_db: Whether to allow all file access when DB
                persistence is unavailable. Defaults to False for safer behavior.
        """
        self.storage_path = os.path.abspath(storage_path)
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.scan_for_malware = scan_for_malware
        self.extract_text = extract_text
        self.db_client = db_client
        self.allow_open_access_without_db = allow_open_access_without_db
        self._files: Dict[str, ContextFile] = {}

        if allowed_extensions is None:
            self.allowed_extensions = {ext.value.lower() for ext in ContextFileType}
        else:
            self.allowed_extensions = {
                ext.lower().lstrip(".") for ext in allowed_extensions if ext
            }

        os.makedirs(self.storage_path, exist_ok=True)

        self.uploads_dir = os.path.join(self.storage_path, "uploads")
        self.quarantine_dir = os.path.join(self.storage_path, "quarantine")

        for dir_path in [self.uploads_dir, self.quarantine_dir]:
            os.makedirs(dir_path, exist_ok=True)

        logger.info(
            "FileUploadHandler initialized with storage path: %s", self.storage_path
        )

    async def handle_upload(
        self,
        file_data: bytes,
        filename: str,
        context_id: str,
        user_id: str,
        mime_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[ContextFile], Optional[str]]:
        """
        Handle file upload with validation and processing.

        Args:
            file_data: Raw file data
            filename: Original filename
            context_id: Context ID to associate file with
            user_id: User ID uploading file
            mime_type: MIME type (detected if not provided)
            metadata: Additional metadata

        Returns:
            Tuple of (ContextFile, error_message)
        """
        safe_filename = self._sanitize_filename(filename)
        detected_mime_type = mime_type or mimetypes.guess_type(safe_filename)[0]
        context_file: Optional[ContextFile] = None
        absolute_path: Optional[str] = None

        try:
            is_valid, validation_error = await self._validate_file(
                file_data=file_data,
                filename=safe_filename,
                mime_type=detected_mime_type,
            )
            if not is_valid:
                await self._quarantine_rejected_upload(
                    file_data=file_data,
                    filename=safe_filename,
                    reason=validation_error or "validation_failed",
                )
                return None, validation_error

            file_type = self._detect_file_type(safe_filename, detected_mime_type)
            if not file_type:
                await self._quarantine_rejected_upload(
                    file_data=file_data,
                    filename=safe_filename,
                    reason="unsupported_file_type",
                )
                return None, "Unsupported file type"

            checksum = hashlib.sha256(file_data).hexdigest()

            existing_file = await self._find_duplicate_file(checksum, user_id)
            if existing_file:
                return existing_file, "File already exists"

            absolute_path, relative_storage_path = await self._save_file(
                file_data=file_data,
                filename=safe_filename,
                checksum=checksum,
            )

            context_file = ContextFile(
                file_id=str(uuid.uuid4()),
                context_id=context_id,
                filename=safe_filename,
                file_type=file_type,
                mime_type=detected_mime_type or "application/octet-stream",
                size_bytes=len(file_data),
                storage_path=relative_storage_path,
                checksum=checksum,
                metadata=metadata or {},
                status=ContextStatus.PROCESSING,
            )

            if self.extract_text:
                await self._process_file(context_file, absolute_path)
            else:
                context_file.error_message = None

            context_file.status = ContextStatus.ACTIVE
            context_file.processed_at = datetime.utcnow()
            self._files[context_file.file_id] = context_file
            await self._persist_file(context_file)

            logger.info(
                "Successfully uploaded file %s for context %s",
                safe_filename,
                context_id,
            )
            return context_file, None

        except Exception as exc:
            logger.exception("Failed to upload file %s", safe_filename)

            if context_file is not None:
                context_file.status = ContextStatus.ERROR
                context_file.error_message = str(exc)
                try:
                    await self._persist_file(context_file)
                except Exception:
                    logger.exception(
                        "Failed to persist failed upload state for %s", safe_filename
                    )

            if absolute_path and os.path.exists(absolute_path):
                try:
                    quarantine_path = self._build_quarantine_path(safe_filename)
                    os.replace(absolute_path, quarantine_path)
                except Exception:
                    logger.exception(
                        "Failed to quarantine file after upload error: %s",
                        safe_filename,
                    )

            return None, str(exc)

    async def get_file(
        self,
        file_id: str,
        user_id: str,
        check_access: bool = True,
    ) -> Optional[ContextFile]:
        """
        Retrieve file information by ID.

        Args:
            file_id: File ID to retrieve
            user_id: User ID requesting file
            check_access: Whether to check access permissions

        Returns:
            ContextFile if found and accessible, None otherwise
        """
        try:
            context_file = self._files.get(file_id)
            if not context_file:
                context_file = await self._load_file(file_id)
                if context_file:
                    self._files[file_id] = context_file

            if not context_file:
                return None

            if context_file.status == ContextStatus.DELETED:
                return None

            if not check_access:
                return context_file

            has_access = await self._check_file_access(context_file.context_id, user_id)
            return context_file if has_access else None

        except Exception as exc:
            logger.error("Failed to get file %s: %s", file_id, exc)
            return None

    async def delete_file(
        self,
        file_id: str,
        user_id: str,
        permanent: bool = False,
    ) -> bool:
        """
        Delete a file (soft delete by default).

        Args:
            file_id: File ID to delete
            user_id: User ID requesting deletion
            permanent: Whether to permanently delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            context_file = await self.get_file(file_id, user_id)
            if not context_file:
                return False

            absolute_path = self._resolve_absolute_storage_path(
                context_file.storage_path
            )

            if permanent:
                if absolute_path and os.path.exists(absolute_path):
                    os.remove(absolute_path)
                await self._delete_file_record(file_id)
                self._files.pop(file_id, None)
            else:
                context_file.status = ContextStatus.DELETED
                context_file.processed_at = datetime.utcnow()
                await self._persist_file(context_file)
                self._files.pop(file_id, None)

            logger.info(
                "%s file %s",
                "Permanently deleted" if permanent else "Soft deleted",
                file_id,
            )
            return True

        except Exception as exc:
            logger.error("Failed to delete file %s: %s", file_id, exc)
            return False

    async def _validate_file(
        self,
        file_data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate file against security and size constraints.

        Args:
            file_data: Raw file data
            filename: Original filename
            mime_type: MIME type

        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(file_data) > self.max_file_size_bytes:
            return (
                False,
                f"File too large. Maximum size is {self.max_file_size_bytes // (1024 * 1024)}MB",
            )

        if len(file_data) == 0:
            return False, "File is empty"

        file_ext = Path(filename).suffix.lower().lstrip(".")
        if file_ext not in self.allowed_extensions:
            return False, f"File type '{file_ext}' not allowed"

        if mime_type:
            mismatch_error = self._validate_mime_extension_consistency(
                filename=filename,
                mime_type=mime_type,
            )
            if mismatch_error:
                return False, mismatch_error

        if self.scan_for_malware:
            is_safe, error = await self._basic_malware_scan(file_data, filename)
            if not is_safe:
                return False, error

        return True, None

    def _detect_file_type(
        self,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> Optional[ContextFileType]:
        """
        Detect file type from filename and MIME type.
        """
        file_ext = Path(filename).suffix.lower().lstrip(".")

        try:
            return ContextFileType(file_ext)
        except ValueError:
            pass

        if mime_type:
            mime_mapping = {
                "application/pdf": ContextFileType.PDF,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ContextFileType.DOCX,
                "text/plain": ContextFileType.TXT,
                "text/markdown": ContextFileType.MD,
                "application/json": ContextFileType.JSON,
                "text/csv": ContextFileType.CSV,
                "application/xml": ContextFileType.XML,
                "text/html": ContextFileType.HTML,
                "text/x-python": ContextFileType.PY,
                "application/javascript": ContextFileType.JS,
                "text/typescript": ContextFileType.TS,
                "text/x-java-source": ContextFileType.JAVA,
                "text/x-c++src": ContextFileType.CPP,
                "image/png": ContextFileType.PNG,
                "image/jpeg": ContextFileType.JPG,
                "image/gif": ContextFileType.GIF,
                "image/svg+xml": ContextFileType.SVG,
                "audio/mpeg": ContextFileType.MP3,
                "audio/wav": ContextFileType.WAV,
                "video/mp4": ContextFileType.MP4,
                "video/x-msvideo": ContextFileType.AVI,
                "video/quicktime": ContextFileType.MOV,
                "application/zip": ContextFileType.ZIP,
                "application/x-tar": ContextFileType.TAR,
                "application/gzip": ContextFileType.GZ,
            }
            return mime_mapping.get(mime_type)

        return None

    async def _save_file(
        self,
        file_data: bytes,
        filename: str,
        checksum: str,
    ) -> Tuple[str, str]:
        """
        Save file to storage.

        Returns:
            Tuple of (absolute_path, relative_path)
        """
        checksum_prefix = checksum[:2]
        checksum_dir = os.path.join(self.uploads_dir, checksum_prefix)
        os.makedirs(checksum_dir, exist_ok=True)

        unique_filename = f"{checksum}_{filename}"
        absolute_path = os.path.abspath(os.path.join(checksum_dir, unique_filename))

        with open(absolute_path, "wb") as file_handle:
            file_handle.write(file_data)

        relative_path = os.path.join("uploads", checksum_prefix, unique_filename)
        return absolute_path, relative_path

    async def _process_file(
        self, context_file: ContextFile, absolute_path: str
    ) -> None:
        """
        Process file to extract text and metadata.
        """
        try:
            extracted_text = await self._extract_text_from_file(
                context_file.file_type,
                absolute_path,
            )
            if extracted_text:
                context_file.extracted_text = extracted_text

            extracted_metadata = await self._extract_metadata_from_file(
                context_file.file_type,
                absolute_path,
            )
            existing_metadata = dict(
                getattr(context_file, "extracted_metadata", {}) or {}
            )
            existing_metadata.update(extracted_metadata or {})
            context_file.extracted_metadata = existing_metadata

        except Exception as exc:
            logger.warning(
                "Failed to process file %s: %s",
                context_file.filename,
                exc,
            )
            context_file.error_message = str(exc)

    async def _extract_text_from_file(
        self,
        file_type: ContextFileType,
        file_path: str,
    ) -> Optional[str]:
        """
        Extract text content from file based on type.
        """
        try:
            if file_type in {
                ContextFileType.TXT,
                ContextFileType.MD,
                ContextFileType.PY,
                ContextFileType.JS,
                ContextFileType.TS,
                ContextFileType.JAVA,
                ContextFileType.CPP,
                ContextFileType.HTML,
                ContextFileType.XML,
            }:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()

            if file_type == ContextFileType.JSON:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return json.dumps(data, indent=2)

            if file_type == ContextFileType.CSV:
                import csv

                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    return "\n".join([",".join(row) for row in rows])

            if file_type == ContextFileType.PDF:
                try:
                    import pymupdf  # type: ignore

                    doc = pymupdf.open(file_path)
                    text_content = ""
                    for page in doc:
                        text_content += page.get_text()  # type: ignore
                    doc.close()
                    return text_content if text_content.strip() else None
                except ImportError:
                    logger.warning("PyMuPDF not installed for PDF text extraction")
                    return None

            if file_type == ContextFileType.DOCX:
                try:
                    from docx import Document  # type: ignore

                    doc = Document(file_path)
                    text_content = ""
                    for paragraph in doc.paragraphs:
                        text_content += paragraph.text + "\n"
                    return text_content if text_content.strip() else None
                except ImportError:
                    logger.warning("python-docx not installed for DOCX text extraction")
                    return None

            if file_type in {
                ContextFileType.PNG,
                ContextFileType.JPG,
                ContextFileType.JPEG,
                ContextFileType.GIF,
                ContextFileType.SVG,
            }:
                logger.info(
                    "Image text extraction is not enabled for %s; metadata-only handling applies",
                    file_type.value,
                )
                return None

            if file_type in {
                ContextFileType.MP3,
                ContextFileType.WAV,
                ContextFileType.MP4,
                ContextFileType.AVI,
                ContextFileType.MOV,
            }:
                logger.info(
                    "Media transcription is not enabled for %s; metadata-only handling applies",
                    file_type.value,
                )
                return None

            if file_type in {
                ContextFileType.ZIP,
                ContextFileType.TAR,
                ContextFileType.GZ,
            }:
                logger.info(
                    "Archive content extraction is not enabled for %s; metadata-only handling applies",
                    file_type.value,
                )
                return None

            return None

        except Exception as exc:
            logger.error("Failed to extract text from %s: %s", file_type.value, exc)
            return None

    async def _extract_metadata_from_file(
        self,
        file_type: ContextFileType,
        file_path: str,
    ) -> Dict[str, Any]:
        """
        Extract metadata from file based on type.
        """
        metadata: Dict[str, Any] = {}

        try:
            stat = os.stat(file_path)
            metadata.update(
                {
                    "size_bytes": stat.st_size,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                }
            )

            if file_type in {
                ContextFileType.PNG,
                ContextFileType.JPG,
                ContextFileType.JPEG,
            }:
                try:
                    from PIL import Image  # type: ignore

                    with Image.open(file_path) as img:
                        metadata.update(
                            {
                                "width": img.width,
                                "height": img.height,
                                "format": img.format,
                                "mode": img.mode,
                            }
                        )
                except ImportError:
                    logger.warning("PIL not installed for image metadata extraction")

            elif file_type in {ContextFileType.MP3, ContextFileType.WAV}:
                try:
                    import mutagen  # type: ignore

                    audio_file = mutagen.File(file_path)
                    if audio_file:
                        metadata.update(
                            {
                                "duration": getattr(audio_file.info, "length", 0),
                                "bitrate": getattr(audio_file.info, "bitrate", 0),
                                "sample_rate": getattr(
                                    audio_file.info, "sample_rate", 0
                                ),
                            }
                        )
                except ImportError:
                    logger.warning(
                        "mutagen not installed for audio metadata extraction"
                    )

            elif file_type in {
                ContextFileType.MP4,
                ContextFileType.AVI,
                ContextFileType.MOV,
            }:
                try:
                    import cv2  # type: ignore

                    cap = cv2.VideoCapture(file_path)
                    if cap.isOpened():
                        metadata.update(
                            {
                                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                "fps": cap.get(cv2.CAP_PROP_FPS),
                                "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                            }
                        )
                        cap.release()
                except ImportError:
                    logger.warning("OpenCV not installed for video metadata extraction")

            return metadata

        except Exception as exc:
            logger.error("Failed to extract metadata from %s: %s", file_type.value, exc)
            return {}

    async def _basic_malware_scan(
        self,
        file_data: bytes,
        filename: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Lightweight prefilter malware scan.

        This is not a substitute for a real antivirus engine.
        """
        executable_signatures = [
            b"MZ",
            b"\x7fELF",
            b"\xca\xfe\xba\xbe",
            b"\xfe\xed\xfa\xce",
        ]

        for signature in executable_signatures:
            if file_data.startswith(signature):
                return False, "Executable file detected"

        suspicious_patterns = [
            b"eval(",
            b"exec(",
            b"system(",
            b"shell_exec(",
        ]

        for pattern in suspicious_patterns:
            if pattern in file_data:
                return False, "Suspicious code pattern detected"

        return True, None

    async def _find_duplicate_file(
        self,
        checksum: str,
        user_id: str,
    ) -> Optional[ContextFile]:
        """
        Find existing file by checksum for a given user.
        """
        if not self._has_db_persistence():
            return None

        assert self.db_client is not None
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT cf.file_id, cf.context_id, cf.filename, cf.file_type, cf.mime_type,
                           cf.size_bytes, cf.storage_path, cf.checksum, cf.extracted_text,
                           cf.extracted_metadata, cf.created_at, cf.processed_at, cf.status,
                           cf.error_message
                    FROM context_files cf
                    JOIN context_entries ce ON ce.id = cf.context_id
                    WHERE cf.checksum = :checksum
                      AND ce.user_id = :user_id
                      AND cf.status != 'deleted'
                    ORDER BY cf.created_at DESC
                    LIMIT 1
                    """
                ),
                {"checksum": checksum, "user_id": user_id},
            )
            row = result.mappings().first()

        return self._row_to_file(dict(row)) if row else None

    def _has_db_persistence(self) -> bool:
        return self.db_client is not None and hasattr(
            self.db_client,
            "get_async_session",
        )

    def _serialize_json(self, value: Any) -> str:
        return json.dumps({} if value is None else value)

    def _row_to_file(self, row: Dict[str, Any]) -> ContextFile:
        return ContextFile(
            file_id=str(row["file_id"]),
            context_id=str(row["context_id"]),
            filename=row["filename"],
            file_type=ContextFileType(row["file_type"]),
            mime_type=row["mime_type"],
            size_bytes=int(row["size_bytes"]),
            storage_path=row["storage_path"],
            checksum=row["checksum"],
            extracted_text=row.get("extracted_text"),
            extracted_metadata=dict(row.get("extracted_metadata") or {}),
            created_at=row.get("created_at") or datetime.utcnow(),
            processed_at=row.get("processed_at"),
            status=ContextStatus(row.get("status") or ContextStatus.PROCESSING.value),
            error_message=row.get("error_message"),
        )

    async def _persist_file(self, context_file: ContextFile) -> None:
        if not self._has_db_persistence():
            return

        assert self.db_client is not None
        async with self.db_client.get_async_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO context_files (
                        file_id, context_id, filename, file_type, mime_type, size_bytes,
                        storage_path, checksum, extracted_text, extracted_metadata,
                        created_at, processed_at, status, error_message
                    ) VALUES (
                        CAST(:file_id AS UUID), CAST(:context_id AS UUID), :filename,
                        :file_type, :mime_type, :size_bytes, :storage_path, :checksum,
                        :extracted_text, CAST(:extracted_metadata AS JSONB),
                        :created_at, :processed_at, :status, :error_message
                    )
                    ON CONFLICT (file_id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        file_type = EXCLUDED.file_type,
                        mime_type = EXCLUDED.mime_type,
                        size_bytes = EXCLUDED.size_bytes,
                        storage_path = EXCLUDED.storage_path,
                        checksum = EXCLUDED.checksum,
                        extracted_text = EXCLUDED.extracted_text,
                        extracted_metadata = EXCLUDED.extracted_metadata,
                        processed_at = EXCLUDED.processed_at,
                        status = EXCLUDED.status,
                        error_message = EXCLUDED.error_message
                    """
                ),
                {
                    "file_id": context_file.file_id,
                    "context_id": context_file.context_id,
                    "filename": context_file.filename,
                    "file_type": context_file.file_type.value,
                    "mime_type": context_file.mime_type,
                    "size_bytes": context_file.size_bytes,
                    "storage_path": context_file.storage_path,
                    "checksum": context_file.checksum,
                    "extracted_text": context_file.extracted_text,
                    "extracted_metadata": self._serialize_json(
                        context_file.extracted_metadata
                    ),
                    "created_at": context_file.created_at,
                    "processed_at": context_file.processed_at,
                    "status": context_file.status.value,
                    "error_message": context_file.error_message,
                },
            )
            await session.commit()

    async def _load_file(self, file_id: str) -> Optional[ContextFile]:
        if not self._has_db_persistence():
            return None

        assert self.db_client is not None
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT file_id, context_id, filename, file_type, mime_type, size_bytes,
                           storage_path, checksum, extracted_text, extracted_metadata,
                           created_at, processed_at, status, error_message
                    FROM context_files
                    WHERE file_id = CAST(:file_id AS UUID)
                    """
                ),
                {"file_id": file_id},
            )
            row = result.mappings().first()

        return self._row_to_file(dict(row)) if row else None

    async def _delete_file_record(self, file_id: str) -> None:
        if not self._has_db_persistence():
            return

        assert self.db_client is not None
        async with self.db_client.get_async_session() as session:
            await session.execute(
                text(
                    "DELETE FROM context_files WHERE file_id = CAST(:file_id AS UUID)"
                ),
                {"file_id": file_id},
            )
            await session.commit()

    async def _check_file_access(self, context_id: str, user_id: str) -> bool:
        """
        Check whether a user can access the context that owns a file.
        """
        if not self._has_db_persistence():
            return self.allow_open_access_without_db

        assert self.db_client is not None
        requester_is_uuid = _is_uuid_like(user_id)
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        ce.user_id,
                        ce.access_level,
                        ce.org_id,
                        owner.tenant_id AS owner_tenant_id,
                        requester.tenant_id AS requester_tenant_id,
                        EXISTS (
                            SELECT 1
                            FROM context_shares cs
                            WHERE cs.context_id = ce.id
                              AND cs.shared_with = :user_id
                              AND (cs.expires_at IS NULL OR cs.expires_at > now())
                        ) AS has_share
                    FROM context_entries ce
                    LEFT JOIN auth_users owner
                        ON owner.user_id = CAST(ce.user_id AS UUID)
                    LEFT JOIN auth_users requester
                        ON requester.user_id = CAST(:requester_uuid AS UUID)
                    WHERE ce.id = CAST(:context_id AS UUID)
                    LIMIT 1
                    """
                ),
                {
                    "context_id": context_id,
                    "user_id": user_id,
                    "requester_uuid": user_id if requester_is_uuid else None,
                },
            )
            row = result.mappings().first()

        if not row:
            return False

        if row["user_id"] == user_id:
            return True

        access_level = row["access_level"]
        if access_level == "public":
            return True
        if access_level == "shared":
            return bool(row["has_share"])
        if access_level in {"team", "organization"}:
            owner_tenant = (
                str(row["owner_tenant_id"]) if row.get("owner_tenant_id") else None
            )
            requester_tenant = (
                str(row["requester_tenant_id"])
                if row.get("requester_tenant_id")
                else None
            )
            if owner_tenant and requester_tenant and owner_tenant == requester_tenant:
                return True
            if (
                row.get("org_id")
                and requester_tenant
                and row["org_id"] == requester_tenant
            ):
                return True
            return False

        return False

    async def _quarantine_rejected_upload(
        self,
        file_data: bytes,
        filename: str,
        reason: str,
    ) -> None:
        """
        Store rejected uploads for review if possible.
        """
        try:
            quarantine_path = self._build_quarantine_path(filename)
            with open(quarantine_path, "wb") as file_handle:
                file_handle.write(file_data)

            metadata_path = f"{quarantine_path}.json"
            with open(metadata_path, "w", encoding="utf-8") as metadata_file:
                json.dump(
                    {
                        "filename": filename,
                        "reason": reason,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    metadata_file,
                    indent=2,
                )
        except Exception:
            logger.exception("Failed to quarantine rejected upload: %s", filename)

    def _build_quarantine_path(self, filename: str) -> str:
        """
        Build a unique quarantine file path.
        """
        safe_filename = self._sanitize_filename(filename)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return os.path.join(
            self.quarantine_dir,
            f"{timestamp}_{uuid.uuid4().hex}_{safe_filename}",
        )

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a user-provided filename for safe storage.
        """
        candidate = Path(str(filename or "")).name
        candidate = candidate.replace("\x00", "").strip()

        if not candidate:
            candidate = f"upload_{uuid.uuid4().hex}"

        candidate = re.sub(r"[^\w.\- ]+", "_", candidate)
        candidate = re.sub(r"\s+", "_", candidate)

        stem = Path(candidate).stem[: self.DEFAULT_MAX_FILENAME_LENGTH]
        suffix = Path(candidate).suffix.lower()

        if not stem:
            stem = f"upload_{uuid.uuid4().hex[:12]}"

        sanitized = f"{stem}{suffix}"
        return sanitized[: self.DEFAULT_MAX_FILENAME_LENGTH + len(suffix)]

    def _validate_mime_extension_consistency(
        self,
        filename: str,
        mime_type: str,
    ) -> Optional[str]:
        """
        Validate whether MIME type and extension are reasonably consistent.
        """
        expected_type = self._detect_file_type(filename, None)
        mime_type_match = self._detect_file_type(filename, mime_type)

        if expected_type is None or mime_type_match is None:
            return None

        if expected_type != mime_type_match:
            return (
                f"File extension and MIME type mismatch: extension implies "
                f"'{expected_type.value}', MIME implies '{mime_type_match.value}'"
            )

        return None

    def _resolve_absolute_storage_path(self, storage_path: str) -> Optional[str]:
        """
        Resolve a stored relative path to an absolute local storage path.
        """
        if not storage_path:
            return None

        if os.path.isabs(storage_path):
            return storage_path

        return os.path.abspath(os.path.join(self.storage_path, storage_path))

    def get_supported_file_types(self) -> List[Dict[str, str]]:
        """
        Get list of supported file types with descriptions.
        """
        file_types: List[Dict[str, str]] = []

        for file_type in ContextFileType:
            file_types.append(
                {
                    "extension": file_type.value,
                    "name": file_type.name,
                    "description": self._get_file_type_description(file_type),
                }
            )

        return file_types

    def _get_file_type_description(self, file_type: ContextFileType) -> str:
        descriptions = {
            ContextFileType.PDF: "PDF Document",
            ContextFileType.DOCX: "Microsoft Word Document",
            ContextFileType.TXT: "Plain Text File",
            ContextFileType.MD: "Markdown Document",
            ContextFileType.JSON: "JSON Data File",
            ContextFileType.CSV: "CSV Data File",
            ContextFileType.XML: "XML Document",
            ContextFileType.HTML: "HTML Document",
            ContextFileType.PY: "Python Source Code",
            ContextFileType.JS: "JavaScript Source Code",
            ContextFileType.TS: "TypeScript Source Code",
            ContextFileType.JAVA: "Java Source Code",
            ContextFileType.CPP: "C++ Source Code",
            ContextFileType.PNG: "PNG Image",
            ContextFileType.JPG: "JPEG Image",
            ContextFileType.JPEG: "JPEG Image",
            ContextFileType.GIF: "GIF Image",
            ContextFileType.SVG: "SVG Vector Image",
            ContextFileType.MP3: "MP3 Audio",
            ContextFileType.WAV: "WAV Audio",
            ContextFileType.MP4: "MP4 Video",
            ContextFileType.AVI: "AVI Video",
            ContextFileType.MOV: "QuickTime Video",
            ContextFileType.ZIP: "ZIP Archive",
            ContextFileType.TAR: "TAR Archive",
            ContextFileType.GZ: "GZIP Archive",
        }
        return descriptions.get(file_type, "Unknown File Type")


def _is_uuid_like(value: str) -> bool:
    """
    Check whether a string can be parsed as a UUID.
    """
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False
