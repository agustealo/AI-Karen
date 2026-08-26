"""
File Upload Service for CoPilot Architecture.

This service provides file upload capabilities for the context management system,
including file validation, processing, and storage.
"""

import asyncio
import logging
import uuid
import hashlib
import os
import mimetypes
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple
from enum import Enum
from dataclasses import dataclass, field
import base64

try:
    from pydantic import BaseModel, Field, validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field, validator

from .file_context_store import (
    ContextError,
    ContextErrorType,
    ContextFile,
    FileContextStore,
    FileContextUpdateRequest,
    FileUploadStatus,
)

logger = logging.getLogger(__name__)


class ProcessingStatus(str, Enum):
    """Processing status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingStep(str, Enum):
    """Processing step enumeration."""

    VALIDATION = "validation"
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    INDEXING = "indexing"
    STORAGE = "storage"


@dataclass
class ProcessingJob:
    """Processing job data model."""

    job_id: str
    context_id: str
    file_id: str
    status: ProcessingStatus
    current_step: ProcessingStep
    progress: float = 0.0  # 0.0 to 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class FileUploadRequest(BaseModel):
    """File upload request model."""

    context_id: str = Field(..., description="Context ID")
    filename: str = Field(..., description="File name")
    file_type: str = Field(..., description="File type")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    content_hash: str = Field(..., description="Content hash for verification")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="File metadata")

    @validator("filename")
    def validate_filename(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("Filename must be a non-empty string")

        # Check for path traversal attempts
        if ".." in v or v.startswith("/"):
            raise ValueError("Filename cannot contain path traversal characters")

        return v

    @validator("file_size")
    def validate_file_size(cls, v):
        if v <= 0:
            raise ValueError("File size must be positive")
        return v


class FileUploadResponse(BaseModel):
    """File upload response model."""

    success: bool = Field(..., description="Upload success status")
    file_id: Optional[str] = Field(None, description="File ID if upload was successful")
    processing_job_id: Optional[str] = Field(None, description="Processing job ID")
    error_message: Optional[str] = Field(None, description="Error message if any")
    correlation_id: Optional[str] = Field(
        None, description="Correlation ID for tracking"
    )


class ProcessingStatusResponse(BaseModel):
    """Processing status response model."""

    success: bool = Field(..., description="Request success status")
    job_id: Optional[str] = Field(None, description="Job ID")
    status: Optional[ProcessingStatus] = Field(None, description="Processing status")
    current_step: Optional[ProcessingStep] = Field(
        None, description="Current processing step"
    )
    progress: Optional[float] = Field(None, description="Progress percentage (0.0-1.0)")
    result: Optional[Dict[str, Any]] = Field(
        None, description="Processing result if completed"
    )
    error_message: Optional[str] = Field(None, description="Error message if any")
    correlation_id: Optional[str] = Field(
        None, description="Correlation ID for tracking"
    )


class FileUploadService:
    """File Upload Service for CoPilot Architecture."""

    def __init__(
        self,
        file_context_store: FileContextStore,
        storage_path: str = "./file_uploads",
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        allowed_file_types: Optional[set] = None,
        enable_processing: bool = True,
    ):
        """
        Initialize File Upload Service.

        Args:
            file_context_store: File-context metadata store
            storage_path: Path for storing uploaded files
            max_file_size: Maximum file size in bytes
            allowed_file_types: Set of allowed file types
            enable_processing: Whether to enable file processing
        """
        self.file_context_store = file_context_store
        self.storage_path = storage_path
        self.max_file_size = max_file_size
        self.allowed_file_types = allowed_file_types or {
            ".txt",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".svg",
            ".mp3",
            ".wav",
            ".ogg",
            ".flac",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }
        self.enable_processing = enable_processing

        # In-memory job storage (in production, this would be a database)
        self._processing_jobs: Dict[str, ProcessingJob] = {}

        # Metrics
        self._metrics = {
            "files_uploaded": 0,
            "files_processed": 0,
            "processing_errors": 0,
            "validation_errors": 0,
            "errors": 0,
        }

        # Create storage directories
        os.makedirs(self.storage_path, exist_ok=True)
        os.makedirs(os.path.join(self.storage_path, "temp"), exist_ok=True)

        # Create subdirectories for different file types
        for file_type in ["documents", "images", "audio", "video", "code", "other"]:
            os.makedirs(os.path.join(self.storage_path, file_type), exist_ok=True)

    async def initialize(self) -> bool:
        """
        Initialize File Upload Service.

        Returns:
            True if initialization was successful
        """
        try:
            logger.info("Initializing File Upload Service")

            # Initialize context manager if not already initialized
            if not self.file_context_store:
                raise ValueError("Context Manager is required")

            logger.info("File Upload Service initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize File Upload Service: {e}")
            self._metrics["errors"] += 1
            raise ContextError(
                message=f"Initialization failed: {str(e)}",
                error_type=ContextErrorType.INTEGRATION_ERROR,
                details={"exception": str(e)},
            )

    async def upload_file(
        self,
        request: FileUploadRequest,
        file_content: bytes,
        correlation_id: Optional[str] = None,
    ) -> FileUploadResponse:
        """
        Upload a file to a context.

        Args:
            request: File upload request
            file_content: Raw file content as bytes
            correlation_id: Correlation ID for tracking

        Returns:
            File upload response
        """
        correlation_id = correlation_id or str(uuid.uuid4())

        try:
            # Validate request
            await self._validate_upload_request(request)

            # Verify content hash
            calculated_hash = self._calculate_content_hash(file_content)
            if calculated_hash != request.content_hash:
                raise ContextError(
                    message="Content hash verification failed",
                    error_type=ContextErrorType.VALIDATION_ERROR,
                    context_id=request.context_id,
                )

            # Get context
            context_response = await self.file_context_store.get_context(
                request.context_id
            )
            if not context_response.success:
                raise ContextError(
                    message=f"Context {request.context_id} not found",
                    error_type=ContextErrorType.NOT_FOUND,
                    context_id=request.context_id,
                )

            context_data = context_response.context_data

            # Generate file ID
            file_id = str(uuid.uuid4())

            # Determine storage path based on file type
            file_ext = os.path.splitext(request.filename)[1].lower()
            storage_dir = self._get_storage_directory(file_ext)
            storage_filename = f"{file_id}{file_ext}"
            storage_path = os.path.join(storage_dir, storage_filename)

            # Write file to storage
            with open(storage_path, "wb") as f:
                f.write(file_content)

            # Create context file
            context_file = ContextFile(
                file_id=file_id,
                filename=request.filename,
                file_type=request.file_type,
                file_size=request.file_size,
                mime_type=request.mime_type,
                content_hash=request.content_hash,
                upload_status=FileUploadStatus.COMPLETED,
                upload_timestamp=datetime.utcnow(),
                metadata=request.metadata,
                storage_path=storage_path,
            )

            # Add file to context
            context_data.files.append(context_file)

            # Update context
            update_request = FileContextUpdateRequest(files=context_data.files)
            await self.file_context_store.update_context(
                context_id=request.context_id, request=update_request
            )

            # Create processing job if enabled
            processing_job_id = None
            if self.enable_processing:
                processing_job_id = await self._create_processing_job(
                    context_id=request.context_id,
                    file_id=file_id,
                    context_file=context_file,
                )

            # Update metrics
            self._metrics["files_uploaded"] += 1

            logger.info(
                f"Uploaded file {request.filename} to context {request.context_id}",
                extra={"correlation_id": correlation_id},
            )

            return FileUploadResponse(
                success=True,
                file_id=file_id,
                processing_job_id=processing_job_id,
                correlation_id=correlation_id,
            )

        except Exception as e:
            self._metrics["errors"] += 1
            error_msg = f"Failed to upload file: {str(e)}"
            logger.error(error_msg, extra={"correlation_id": correlation_id})

            return FileUploadResponse(
                success=False, error_message=error_msg, correlation_id=correlation_id
            )

    async def get_processing_status(
        self, job_id: str, correlation_id: Optional[str] = None
    ) -> ProcessingStatusResponse:
        """
        Get the status of a processing job.

        Args:
            job_id: Job identifier
            correlation_id: Correlation ID for tracking

        Returns:
            Processing status response
        """
        correlation_id = correlation_id or str(uuid.uuid4())

        try:
            job = self._processing_jobs.get(job_id)
            if not job:
                error_msg = f"Processing job {job_id} not found"
                logger.warning(error_msg, extra={"correlation_id": correlation_id})
                return ProcessingStatusResponse(
                    success=False,
                    error_message=error_msg,
                    correlation_id=correlation_id,
                )

            logger.debug(
                f"Retrieved processing job {job_id} with status {job.status}",
                extra={"correlation_id": correlation_id},
            )

            return ProcessingStatusResponse(
                success=True,
                job_id=job_id,
                status=job.status,
                current_step=job.current_step,
                progress=job.progress,
                result=job.result,
                error_message=job.error_message,
                correlation_id=correlation_id,
            )

        except Exception as e:
            self._metrics["errors"] += 1
            error_msg = f"Failed to get processing status for job {job_id}: {str(e)}"
            logger.error(error_msg, extra={"correlation_id": correlation_id})

            return ProcessingStatusResponse(
                success=False, error_message=error_msg, correlation_id=correlation_id
            )

    async def _validate_upload_request(self, request: FileUploadRequest) -> None:
        """
        Validate a file upload request.

        Args:
            request: File upload request to validate

        Raises:
            ContextError: If validation fails
        """
        # Validate file size
        if request.file_size > self.max_file_size:
            raise ContextError(
                message=f"File size {request.file_size} exceeds maximum allowed size of {self.max_file_size}",
                error_type=ContextErrorType.VALIDATION_ERROR,
                context_id=request.context_id,
            )

        # Validate file type
        file_ext = os.path.splitext(request.filename)[1].lower()
        if file_ext not in self.allowed_file_types:
            raise ContextError(
                message=f"File type {file_ext} is not allowed",
                error_type=ContextErrorType.VALIDATION_ERROR,
                context_id=request.context_id,
            )

        # Validate MIME type
        if not mimetypes.guess_type(request.filename):
            # If MIME type cannot be guessed, use the provided one
            pass
        else:
            guessed_mime = mimetypes.guess_type(request.filename)
            if guessed_mime and guessed_mime != request.mime_type:
                logger.warning(
                    f"MIME type mismatch for {request.filename}: provided {request.mime_type}, guessed {guessed_mime}",
                    extra={"context_id": request.context_id},
                )

    def _calculate_content_hash(self, content: bytes) -> str:
        """
        Calculate SHA-256 hash of content.

        Args:
            content: File content as bytes

        Returns:
            Content hash as hex string
        """
        return hashlib.sha256(content).hexdigest()

    def _get_storage_directory(self, file_ext: str) -> str:
        """
        Get the appropriate storage directory based on file extension.

        Args:
            file_ext: File extension

        Returns:
            Storage directory path
        """
        document_extensions = {
            ".txt",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
        }
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"}
        audio_extensions = {".mp3", ".wav", ".ogg", ".flac"}
        video_extensions = {".mp4", ".avi", ".mov", ".wmv", ".flv"}
        code_extensions = {
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }

        if file_ext in document_extensions:
            return os.path.join(self.storage_path, "documents")
        elif file_ext in image_extensions:
            return os.path.join(self.storage_path, "images")
        elif file_ext in audio_extensions:
            return os.path.join(self.storage_path, "audio")
        elif file_ext in video_extensions:
            return os.path.join(self.storage_path, "video")
        elif file_ext in code_extensions:
            return os.path.join(self.storage_path, "code")
        else:
            return os.path.join(self.storage_path, "other")

    async def _create_processing_job(
        self, context_id: str, file_id: str, context_file
    ) -> str:
        """
        Create a processing job for a file.

        Args:
            context_id: Context ID
            file_id: File ID
            context_file: Context file object

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())

        # Create processing job
        job = ProcessingJob(
            job_id=job_id,
            context_id=context_id,
            file_id=file_id,
            status=ProcessingStatus.PENDING,
            current_step=ProcessingStep.VALIDATION,
        )

        # Store job
        self._processing_jobs[job_id] = job

        # Start processing in background
        asyncio.create_task(self._process_file(job_id))

        logger.info(f"Created processing job {job_id} for file {file_id}")
        return job_id

    async def _process_file(self, job_id: str) -> None:
        """
        Process a file in the background.

        Args:
            job_id: Job ID
        """
        try:
            job = self._processing_jobs.get(job_id)
            if not job:
                logger.error(f"Processing job {job_id} not found")
                return

            # Update job status
            job.status = ProcessingStatus.PROCESSING
            job.started_at = datetime.utcnow()

            # Process each step
            for step in [
                ProcessingStep.VALIDATION,
                ProcessingStep.EXTRACTION,
                ProcessingStep.ANALYSIS,
                ProcessingStep.INDEXING,
                ProcessingStep.STORAGE,
            ]:
                try:
                    job.current_step = step
                    job.progress = 0.0

                    # Process step
                    step_result = await self._process_step(job, step)

                    # Update job with step result
                    if step_result:
                        if not job.result:
                            job.result = {}
                        job.result[step.value] = step_result

                    # Update progress
                    job.progress = (list(ProcessingStep).index(step) + 1) / len(
                        ProcessingStep
                    )

                except Exception as e:
                    job.status = ProcessingStatus.FAILED
                    job.error_message = f"Failed to process step {step.value}: {str(e)}"
                    self._metrics["processing_errors"] += 1
                    logger.error(
                        f"Failed to process step {step.value} for job {job_id}: {e}"
                    )
                    return

            # Mark job as completed
            job.status = ProcessingStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.progress = 1.0

            # Update metrics
            self._metrics["files_processed"] += 1

            logger.info(f"Completed processing job {job_id}")

        except Exception as e:
            if job_id in self._processing_jobs:
                job = self._processing_jobs[job_id]
                job.status = ProcessingStatus.FAILED
                job.error_message = f"Processing failed: {str(e)}"

            self._metrics["processing_errors"] += 1
            logger.error(f"Failed to process file for job {job_id}: {e}")

    async def _process_step(
        self, job: ProcessingJob, step: ProcessingStep
    ) -> Optional[Dict[str, Any]]:
        """
        Process a specific step for a file.

        Args:
            job: Processing job
            step: Processing step

        Returns:
            Step result or None
        """
        # Get context file
        context_response = await self.file_context_store.get_context(job.context_id)
        if not context_response.success:
            raise ContextError(
                message=f"Context {job.context_id} not found",
                error_type=ContextErrorType.NOT_FOUND,
                context_id=job.context_id,
            )

        context_data = context_response.context_data
        context_file = next(
            (f for f in context_data.files if f.file_id == job.file_id), None
        )
        if not context_file:
            raise ContextError(
                message=f"File {job.file_id} not found in context",
                error_type=ContextErrorType.NOT_FOUND,
                context_id=job.context_id,
            )

        # Process based on step type
        if step == ProcessingStep.VALIDATION:
            return await self._validate_file(context_file)
        elif step == ProcessingStep.EXTRACTION:
            return await self._extract_content(context_file)
        elif step == ProcessingStep.ANALYSIS:
            return await self._analyze_content(context_file)
        elif step == ProcessingStep.INDEXING:
            return await self._index_content(context_file)
        elif step == ProcessingStep.STORAGE:
            return await self._store_content(context_file)
        else:
            raise ValueError(f"Unknown processing step: {step}")

    async def _validate_file(self, context_file) -> Dict[str, Any]:
        """
        Validate a file.

        Args:
            context_file: Context file object

        Returns:
            Validation result
        """
        # Check if file exists
        if not context_file.storage_path or not os.path.exists(
            context_file.storage_path
        ):
            raise ContextError(
                message=f"File {context_file.filename} not found at {context_file.storage_path}",
                error_type=ContextErrorType.VALIDATION_ERROR,
                context_id=context_file.context_id,
            )

        # Check file size
        actual_size = os.path.getsize(context_file.storage_path)
        if actual_size != context_file.file_size:
            raise ContextError(
                message=f"File size mismatch for {context_file.filename}: expected {context_file.file_size}, got {actual_size}",
                error_type=ContextErrorType.VALIDATION_ERROR,
                context_id=context_file.context_id,
            )

        # Validate file content hash
        with open(context_file.storage_path, "rb") as f:
            content = f.read()

        actual_hash = self._calculate_content_hash(content)
        if actual_hash != context_file.content_hash:
            raise ContextError(
                message=f"Content hash mismatch for {context_file.filename}",
                error_type=ContextErrorType.VALIDATION_ERROR,
                context_id=context_file.context_id,
            )

        return {"valid": True, "file_size": actual_size, "content_hash": actual_hash}

    async def _extract_content(self, context_file) -> Dict[str, Any]:
        """
        Extract content from a file.

        Args:
            context_file: Context file object

        Returns:
            Extraction result
        """
        file_ext = os.path.splitext(context_file.filename)[1].lower()

        # Text files
        if file_ext in {
            ".txt",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }:
            with open(context_file.storage_path, "r", encoding="utf-8") as f:
                content = f.read()

            return {
                "content_type": "text",
                "content": content,
                "content_length": len(content),
            }

        # For other file types, we would use specialized libraries
        # For now, we'll return basic metadata
        return {
            "content_type": "binary",
            "content_length": context_file.file_size,
            "extraction_method": "metadata_only",
        }

    async def _analyze_content(self, context_file) -> Dict[str, Any]:
        """
        Analyze content of a file.

        Args:
            context_file: Context file object

        Returns:
            Analysis result
        """
        # For text files, perform basic analysis
        file_ext = os.path.splitext(context_file.filename)[1].lower()

        if file_ext in {
            ".txt",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }:
            with open(context_file.storage_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Basic analysis
            word_count = len(content.split())
            line_count = len(content.splitlines())
            char_count = len(content)

            return {
                "content_type": "text",
                "word_count": word_count,
                "line_count": line_count,
                "char_count": char_count,
                "language": "unknown",  # In a real implementation, we would detect language
            }

        # For other file types, we would use specialized analysis
        # For now, we'll return basic metadata
        return {
            "content_type": "binary",
            "analysis_method": "metadata_only",
            "file_type": context_file.mime_type,
        }

    async def _index_content(self, context_file) -> Dict[str, Any]:
        """
        Index content for search.

        Args:
            context_file: Context file object

        Returns:
            Indexing result
        """
        # For text files, create a basic index
        file_ext = os.path.splitext(context_file.filename)[1].lower()

        if file_ext in {
            ".txt",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }:
            with open(context_file.storage_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Simple keyword extraction
            words = content.lower().split()
            word_freq = {}

            for word in words:
                # Clean word
                clean_word = "".join(c for c in word if c.isalnum())
                if len(clean_word) > 3:  # Only consider words longer than 3 characters
                    word_freq[clean_word] = word_freq.get(clean_word, 0) + 1

            # Get top keywords
            top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[
                :10
            ]

            return {
                "content_type": "text",
                "indexed": True,
                "keywords": [word for word, freq in top_keywords],
                "keyword_freq": top_keywords,
            }

        # For other file types, we would use specialized indexing
        # For now, we'll return basic metadata
        return {
            "content_type": "binary",
            "indexed": False,
            "indexing_method": "metadata_only",
        }

    async def _store_content(self, context_file) -> Dict[str, Any]:
        """
        Store processed content.

        Args:
            context_file: Context file object

        Returns:
            Storage result
        """
        # In a real implementation, this would store processed content
        # in a searchable database or index

        # For now, we'll just return success
        return {
            "stored": True,
            "storage_method": "filesystem",
            "storage_path": context_file.storage_path,
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get service metrics.

        Returns:
            Service metrics
        """
        active_jobs = len(
            [
                j
                for j in self._processing_jobs.values()
                if j.status == ProcessingStatus.PROCESSING
            ]
        )

        return {
            **self._metrics,
            "active_processing_jobs": active_jobs,
            "total_processing_jobs": len(self._processing_jobs),
            "storage_path": self.storage_path,
            "max_file_size": self.max_file_size,
            "allowed_file_types": list(self.allowed_file_types),
        }

    async def cleanup_old_files(
        self, days: int = 30, correlation_id: Optional[str] = None
    ) -> int:
        """
        Clean up old files.

        Args:
            days: Number of days after which files are considered old
            correlation_id: Correlation ID for tracking

        Returns:
            Number of files cleaned up
        """
        correlation_id = correlation_id or str(uuid.uuid4())

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            cleanup_count = 0

            # This would typically iterate through all files and delete old ones
            # For now, we'll just log the attempt
            logger.info(
                f"Cleaning up files older than {days} days",
                extra={"correlation_id": correlation_id},
            )

            return cleanup_count

        except Exception as e:
            self._metrics["errors"] += 1
            error_msg = f"Failed to cleanup old files: {str(e)}"
            logger.error(error_msg, extra={"correlation_id": correlation_id})
            return 0

    async def shutdown(self) -> None:
        """Shutdown File Upload Service."""
        try:
            logger.info("Shutting down File Upload Service")

            # Cancel active processing jobs
            for job_id, job in self._processing_jobs.items():
                if job.status == ProcessingStatus.PROCESSING:
                    job.status = ProcessingStatus.FAILED
                    job.error_message = "Service shutdown"

            logger.info("File Upload Service shutdown completed")

        except Exception as e:
            logger.error(f"Error during File Upload Service shutdown: {e}")
