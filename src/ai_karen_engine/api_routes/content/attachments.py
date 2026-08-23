"""
Enhanced FastAPI routes for file attachment with AG-UI and hook integration.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from tempfile import SpooledTemporaryFile

from ai_karen_engine.services.tooling.file_attachment_service import (
    FileAttachmentService,
    FileProcessingResult,
    FileType,
    FileUploadRequest,
    FileUploadResponse,
    ProcessingStatus,
    get_hook_enabled_file_service,
    MultimediaService,
    MediaProcessingRequest,
    MediaProcessingResponse,
    MediaType,
    ProcessingCapability,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_service_error_response,
    create_validation_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, File, Form, HTTPException, Query, UploadFile, responses = import_fastapi(
    "APIRouter", "File", "Form", "HTTPException", "Query", "UploadFile", "responses"
)
StreamingResponse = responses.StreamingResponse
JSONResponse = responses.JSONResponse
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = get_logger(__name__)

router = APIRouter(tags=["file-attachments"])

# Initialize services
file_service = FileAttachmentService()
multimedia_service = MultimediaService()


# Request/Response Models
class FileUploadMetadata(BaseModel):
    """Metadata for file upload."""

    conversation_id: str = Field(..., description="Conversation ID")
    user_id: str = Field(..., description="User ID")
    description: Optional[str] = Field(None, description="File description")
    tags: List[str] = Field(default_factory=list, description="File tags")


class FileListResponse(BaseModel):
    """Response for file listing."""

    files: List[Dict[str, Any]] = Field(..., description="List of files")
    total_count: int = Field(..., description="Total number of files")
    has_more: bool = Field(..., description="Whether there are more files")


class MultimediaProcessingRequest(BaseModel):
    """Request for multimedia processing."""

    capabilities: List[ProcessingCapability] = Field(
        ..., description="Requested processing capabilities"
    )
    options: Dict[str, Any] = Field(
        default_factory=dict, description="Processing options"
    )
    priority: int = Field(1, ge=1, le=5, description="Processing priority")


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    metadata: str = Form(...),  # JSON string of FileUploadMetadata
):
    """Upload a file attachment."""
    try:
        import json

        # Parse metadata
        try:
            metadata_dict = json.loads(metadata)
            file_metadata = FileUploadMetadata(**metadata_dict)
        except (json.JSONDecodeError, ValueError) as e:
            error_response = create_validation_error_response(
                field="metadata",
                message="Invalid metadata format",
                details={"error": str(e)},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.VALIDATION_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        # Stream file content to temporary file to enforce size limits
        max_size = file_service.max_file_size
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB

        with SpooledTemporaryFile(max_size=max_size) as tmp:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_size:
                    error_response = create_validation_error_response(
                        field="file",
                        message=f"File size exceeds maximum allowed size of {max_size} bytes",
                        details={"max_size": max_size},
                    )
                    raise HTTPException(
                        status_code=get_http_status_for_error_code(
                            WebAPIErrorCode.VALIDATION_ERROR
                        ),
                        detail=error_response.model_dump(mode="json"),
                    )
                tmp.write(chunk)

            tmp.seek(0)

            # Create upload request
            upload_request = FileUploadRequest(
                conversation_id=file_metadata.conversation_id,
                user_id=file_metadata.user_id,
                filename=file.filename or "unknown",
                content_type=file.content_type or "application/octet-stream",
                file_size=file_size,
                description=file_metadata.description,
                metadata={"tags": file_metadata.tags},
            )

            # Upload file using streamed content
            result = await file_service.upload_file(upload_request, tmp)

        if not result.success:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception(result.message),
                error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
                user_message=result.message,
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.INTERNAL_SERVER_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File upload failed", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="File upload failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/{file_id}/info", response_model=FileProcessingResult)
async def get_file_info(file_id: str):
    """Get file processing information."""
    try:
        result = await file_service.get_file_info(file_id)

        if not result:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception("File not found"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The requested file could not be found.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get file info", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get file information. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/{file_id}/download")
async def download_file(file_id: str):
    """Download file content."""
    try:
        # Get file info first
        file_info = await file_service.get_file_info(file_id)
        if not file_info:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception("File not found"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The requested file could not be found.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        # Get file content
        file_content = await file_service.get_file_content(file_id)
        if not file_content:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception("File content not available"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The file content is not available.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        # Get file metadata for proper response
        metadata = await file_service.get_metadata(file_id)
        if not metadata:
            filename = f"file_{file_id}"
            mime_type = "application/octet-stream"
        else:
            filename = metadata.original_filename
            mime_type = metadata.mime_type

        # Return file as streaming response
        def generate():
            yield file_content

        return StreamingResponse(
            generate(),
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File download failed", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="File download failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/{file_id}/thumbnail")
async def get_file_thumbnail(file_id: str):
    """Get file thumbnail."""
    try:
        thumbnail_content = await file_service.get_thumbnail(file_id)

        if not thumbnail_content:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception("Thumbnail not available"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="Thumbnail is not available for this file.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        def generate():
            yield thumbnail_content

        return StreamingResponse(
            generate(),
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f"inline; filename=thumbnail_{file_id}.jpg"
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Thumbnail retrieval failed", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get thumbnail. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{file_id}/process", response_model=MediaProcessingResponse)
async def process_multimedia(file_id: str, request: MultimediaProcessingRequest):
    """Process multimedia file with advanced capabilities."""
    try:
        # Get file info
        file_info = await file_service.get_file_info(file_id)
        if not file_info:
            error_response = create_service_error_response(
                service_name="multimedia",
                error=Exception("File not found"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The requested file could not be found.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        # Get file metadata to determine media type
        metadata = await file_service.get_metadata(file_id)
        if not metadata:
            error_response = create_service_error_response(
                service_name="multimedia",
                error=Exception("File metadata not available"),
                error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
                user_message="File metadata is not available.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.INTERNAL_SERVER_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        # Determine media type
        media_type = None
        if metadata.file_type.value == "image":
            media_type = MediaType.IMAGE
        elif metadata.file_type.value == "audio":
            media_type = MediaType.AUDIO
        elif metadata.file_type.value == "video":
            media_type = MediaType.VIDEO
        else:
            error_response = create_validation_error_response(
                field="file_type",
                message="File type not supported for multimedia processing",
                details={"file_type": metadata.file_type.value},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.VALIDATION_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        # Create processing request
        processing_request = MediaProcessingRequest(
            file_id=file_id,
            media_type=media_type,
            capabilities=request.capabilities,
            options=request.options,
            priority=request.priority,
        )

        # Get file path
        file_path = file_service.storage_path / "files" / metadata.filename

        # Process multimedia
        result = await multimedia_service.process_media(processing_request, file_path)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Multimedia processing failed", error=str(e))
        error_response = create_service_error_response(
            service_name="multimedia",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Multimedia processing failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/", response_model=FileListResponse)
async def list_files(
    conversation_id: Optional[str] = Query(
        None, description="Filter by conversation ID"
    ),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    file_type: Optional[FileType] = Query(None, description="Filter by file type"),
    processing_status: Optional[ProcessingStatus] = Query(
        None, description="Filter by processing status"
    ),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of files"),
    offset: int = Query(0, ge=0, description="Number of files to skip"),
):
    """List files with optional filtering."""
    try:
        # Get all files from service
        all_files = []

        files_dict = await file_service.list_files()
        for file_id, metadata in files_dict.items():
            # Apply filters
            if file_type and metadata.file_type != file_type:
                continue
            if processing_status and metadata.processing_status != processing_status:
                continue

            file_info = {
                "file_id": file_id,
                "filename": metadata.original_filename,
                "file_size": metadata.file_size,
                "mime_type": metadata.mime_type,
                "file_type": metadata.file_type.value,
                "processing_status": metadata.processing_status.value,
                "upload_timestamp": metadata.upload_timestamp.isoformat(),
                "has_thumbnail": metadata.thumbnail_path is not None,
                "preview_available": metadata.preview_available,
                "extracted_content_available": metadata.extracted_content is not None,
            }

            all_files.append(file_info)

        # Sort by upload timestamp (newest first)
        all_files.sort(key=lambda x: x["upload_timestamp"], reverse=True)

        # Apply pagination
        paginated_files = all_files[offset : offset + limit]

        return FileListResponse(
            files=paginated_files,
            total_count=len(all_files),
            has_more=len(all_files) > offset + limit,
        )

    except Exception as e:
        logger.exception("Failed to list files", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to list files. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.delete("/{file_id}")
async def delete_file(file_id: str):
    """Delete a file attachment."""
    try:
        success = await file_service.delete_file(file_id)

        if not success:
            error_response = create_service_error_response(
                service_name="file_attachment",
                error=Exception("File not found or deletion failed"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The requested file could not be found or deleted.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "File deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("File deletion failed", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="File deletion failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/capabilities")
async def get_multimedia_capabilities():
    """Get available multimedia processing capabilities."""
    try:
        capabilities = multimedia_service.get_available_capabilities()
        stats = multimedia_service.get_processing_stats()

        return {
            "available_capabilities": [cap.value for cap in capabilities],
            "processing_stats": stats,
            "supported_media_types": [media_type.value for media_type in MediaType],
        }

    except Exception as e:
        logger.exception("Failed to get capabilities", error=str(e))
        error_response = create_service_error_response(
            service_name="multimedia",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get capabilities. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/stats")
async def get_file_storage_stats():
    """Get file storage statistics."""
    try:
        stats = await file_service.get_storage_stats()

        return {"storage_stats": stats, "service_status": "operational"}

    except Exception as e:
        logger.exception("Failed to get storage stats", error=str(e))
        error_response = create_service_error_response(
            service_name="file_attachment",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get storage statistics. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )
