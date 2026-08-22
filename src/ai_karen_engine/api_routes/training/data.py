"""
API routes for training data management.

This module provides REST API endpoints for managing training datasets,
including creation, upload, validation, format conversion, version control,
and quality assessment.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from fastapi.responses import Response, StreamingResponse
try:
    from pydantic import BaseModel, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field
import io

from ai_karen_engine.learning.training_data_manager import (
    TrainingDataManager,
    DataFormat,
    ValidationReport,
    QualityMetrics,
    DatasetMetadata,
    DatasetVersion
)
from ai_karen_engine.learning.autonomous_learner import TrainingExample, LearningDataType
from ai_karen_engine.core.cortex.analysis import SpacyAnalyzer
from ai_karen_engine.core.memory.memory_service import WebUIMemoryService
from ai_karen_engine.auth.rbac_middleware import (
    require_permission, get_current_user, Permission, 
    check_training_access, check_data_access
)
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.services.audit.training_audit_logger import get_training_audit_logger

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/training-data", tags=["training-data"])

# Initialize audit logger
training_audit_logger = get_training_audit_logger()

# Global training data manager instance
_training_manager: Optional[TrainingDataManager] = None


def get_training_manager() -> TrainingDataManager:
    """Get or create training data manager instance."""
    global _training_manager
    if _training_manager is None:
        _training_manager = TrainingDataManager()
    return _training_manager


def _create_autonomous_learner() -> "AutonomousLearner":
    """Create an autonomous learner directly from the live training components."""
    from ai_karen_engine.learning.autonomous_learner import AutonomousLearner

    return AutonomousLearner(
        spacy_analyzer=SpacyAnalyzer(),
        memory_service=WebUIMemoryService(),
    )


# Pydantic models for API

class CreateDatasetRequest(BaseModel):
    """Request model for creating a new dataset."""
    name: str = Field(..., description="Dataset name")
    description: str = Field(..., description="Dataset description")
    format: DataFormat = Field(DataFormat.JSON, description="Data format")
    tags: Optional[List[str]] = Field(None, description="Dataset tags")


class CreateDatasetResponse(BaseModel):
    """Response model for dataset creation."""
    dataset_id: str = Field(..., description="Created dataset ID")
    message: str = Field(..., description="Success message")


class CreateCuratedDatasetRequest(BaseModel):
    """Request model for building a dataset from curated autonomous-learning outputs."""

    name: str = Field(..., description="Dataset name")
    description: str = Field(..., description="Dataset description")
    tenant_id: Optional[str] = Field(None, description="Tenant scope for curated memory")
    min_confidence: float = Field(0.7, ge=0.0, le=1.0)
    max_examples: int = Field(250, ge=1, le=5000)
    tags: Optional[List[str]] = Field(None, description="Dataset tags")


class CreateCuratedDatasetResponse(BaseModel):
    """Response for curated memory dataset creation."""

    dataset_id: str
    version_id: str
    example_count: int
    quality_score: float
    message: str


class UploadDatasetRequest(BaseModel):
    """Request model for uploading dataset data."""
    dataset_id: str = Field(..., description="Target dataset ID")
    data: List[Dict[str, Any]] = Field(..., description="Training examples")
    format: DataFormat = Field(DataFormat.JSON, description="Data format")
    version_description: str = Field("API upload", description="Version description")


class UploadDatasetResponse(BaseModel):
    """Response model for dataset upload."""
    version_id: str = Field(..., description="Created version ID")
    validation_report: Dict[str, Any] = Field(..., description="Validation report")
    message: str = Field(..., description="Success message")


class ValidationResponse(BaseModel):
    """Response model for dataset validation."""
    validation_report: Dict[str, Any] = Field(..., description="Validation report")
    quality_metrics: Dict[str, Any] = Field(..., description="Quality metrics")


class DatasetListResponse(BaseModel):
    """Response model for dataset listing."""
    datasets: List[Dict[str, Any]] = Field(..., description="List of datasets")
    total: int = Field(..., description="Total number of datasets")


class VersionListResponse(BaseModel):
    """Response model for version listing."""
    versions: List[Dict[str, Any]] = Field(..., description="List of versions")
    total: int = Field(..., description="Total number of versions")


class ConvertFormatRequest(BaseModel):
    """Request model for format conversion."""
    dataset_id: str = Field(..., description="Source dataset ID")
    target_format: DataFormat = Field(..., description="Target format")


# RBAC-protected endpoints

@router.post("/datasets", response_model=CreateDatasetResponse)
async def create_dataset(
    request: CreateDatasetRequest,
    current_user: UserData = Depends(get_current_user)
) -> CreateDatasetResponse:
    """Create a new training dataset (requires DATA_WRITE permission)."""
    # Check permissions
    if not check_data_access(current_user, "write"):
        training_audit_logger.log_permission_denied(
            user=current_user,
            resource_type="dataset",
            resource_id="new",
            permission_required="data:write"
        )
        raise HTTPException(status_code=403, detail="DATA_WRITE permission required")
    
    try:
        manager = get_training_manager()
        dataset_id = manager.create_dataset(
            name=request.name,
            description=request.description,
            format=request.format,
            tags=request.tags or [],
            created_by=current_user.user_id
        )
        
        # Audit log
        training_audit_logger.log_training_data_uploaded(
            user=current_user,
            dataset_id=dataset_id,
            dataset_name=request.name,
            record_count=0,
            file_size=0,
            data_format=request.format.value
        )
        
        return CreateDatasetResponse(
            dataset_id=dataset_id,
            message=f"Dataset '{request.name}' created successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to create dataset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    current_user: UserData = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
) -> DatasetListResponse:
    """List training datasets (requires DATA_READ permission)."""
    # Check permissions
    if not check_data_access(current_user, "read"):
        training_audit_logger.log_permission_denied(
            user=current_user,
            resource_type="dataset",
            resource_id="list",
            permission_required="data:read"
        )
        raise HTTPException(status_code=403, detail="DATA_READ permission required")
    
    try:
        manager = get_training_manager()
        datasets = manager.list_datasets(
            user_id=current_user.user_id,
            tenant_id=current_user.tenant_id,
            limit=limit,
            offset=offset
        )
        
        return DatasetListResponse(
            datasets=[dataset.to_dict() for dataset in datasets],
            total=len(datasets)
        )
        
    except Exception as e:
        logger.error(f"Failed to list datasets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    current_user: UserData = Depends(get_current_user)
) -> Dict[str, str]:
    """Delete a training dataset (requires DATA_DELETE permission)."""
    # Check permissions
    if not check_data_access(current_user, "delete"):
        training_audit_logger.log_permission_denied(
            user=current_user,
            resource_type="dataset",
            resource_id=dataset_id,
            permission_required="data:delete"
        )
        raise HTTPException(status_code=403, detail="DATA_DELETE permission required")
    
    try:
        manager = get_training_manager()
        success = manager.delete_dataset(
            dataset_id=dataset_id,
            user_id=current_user.user_id
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Dataset not found or access denied")
        
        # Audit log
        training_audit_logger.log_training_data_deleted(
            user=current_user,
            dataset_id=dataset_id,
            dataset_name=f"dataset_{dataset_id}"
        )
        
        return {"message": f"Dataset {dataset_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete dataset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/datasets/from-curated-memory", response_model=CreateCuratedDatasetResponse)
async def create_dataset_from_curated_memory(
    request: CreateCuratedDatasetRequest,
    current_user: UserData = Depends(get_current_user),
) -> CreateCuratedDatasetResponse:
    """Create a training dataset from curated autonomous-learning memory outputs."""

    if not check_data_access(current_user, "write"):
        training_audit_logger.log_permission_denied(
            user=current_user,
            resource_type="dataset",
            resource_id="curated-memory",
            permission_required="data:write",
        )
        raise HTTPException(status_code=403, detail="DATA_WRITE permission required")

    try:
        tenant_id = request.tenant_id or current_user.tenant_id or current_user.user_id
        learner = _create_autonomous_learner()
        curated_metadata = await learner.metadata_collector.curate_training_data(
            tenant_id=tenant_id,
            min_confidence=request.min_confidence,
            max_examples=request.max_examples,
        )
        training_examples = await learner.training_pipeline.create_training_examples(
            curated_metadata
        )

        if not training_examples:
            raise HTTPException(
                status_code=400,
                detail="No curated training examples available for dataset creation",
            )

        manager = get_training_manager()
        dataset_id, version_id, validation_report = manager.create_dataset_from_examples(
            name=request.name,
            description=request.description,
            created_by=current_user.user_id,
            examples=training_examples,
            tags=(request.tags or []) + ["curated-memory"],
            provenance={
                "source": "autonomous_learner",
                "tenant_id": tenant_id,
                "curated_metadata_count": len(curated_metadata),
                "created_via": "training_data_routes",
            },
        )

        training_audit_logger.log_training_data_uploaded(
            user=current_user,
            dataset_id=dataset_id,
            dataset_name=request.name,
            record_count=len(training_examples),
            file_size=0,
            data_format=DataFormat.JSON.value,
        )

        return CreateCuratedDatasetResponse(
            dataset_id=dataset_id,
            version_id=version_id,
            example_count=len(training_examples),
            quality_score=validation_report.quality_score,
            message=f"Curated dataset '{request.name}' created successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create curated dataset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EnhanceDatasetRequest(BaseModel):
    """Request model for dataset enhancement."""
    dataset_id: str = Field(..., description="Dataset to enhance")
    version: Optional[str] = Field(None, description="Specific version")
    create_new_version: bool = Field(True, description="Create new version for enhanced data")


class CreateVersionRequest(BaseModel):
    """Request model for creating a new version."""
    dataset_id: str = Field(..., description="Dataset ID")
    source_version: str = Field(..., description="Source version ID")
    description: str = Field(..., description="Version description")
    modifications: Optional[Dict[str, Any]] = Field(None, description="Modifications to apply")


# API Routes

async def _legacy_create_dataset(
    request: CreateDatasetRequest,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Create a new training dataset."""
    try:
        manager = get_training_manager()
        
        dataset_id = manager.create_dataset(
            name=request.name,
            description=request.description,
            created_by=current_user.get("user_id", "unknown"),
            format=request.format,
            tags=request.tags
        )
        
        logger.info(f"Created dataset {dataset_id}: {request.name}")
        
        return CreateDatasetResponse(
            dataset_id=dataset_id,
            message=f"Dataset '{request.name}' created successfully"
        )
        
    except Exception as e:
        logger.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create dataset: {str(e)}")


async def _legacy_list_datasets(
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """List all training datasets."""
    try:
        manager = get_training_manager()
        
        # Get all dataset metadata files
        datasets = []
        metadata_dir = manager.metadata_dir
        
        if metadata_dir.exists():
            for metadata_file in metadata_dir.glob("*.json"):
                try:
                    dataset_id = metadata_file.stem
                    metadata = manager._load_dataset_metadata(dataset_id)
                    if metadata:
                        datasets.append(metadata.to_dict())
                except Exception as e:
                    logger.warning(f"Error loading dataset metadata {metadata_file}: {e}")
                    continue
        
        # Sort by creation date
        datasets.sort(key=lambda d: d.get('created_at', ''), reverse=True)
        
        return DatasetListResponse(
            datasets=datasets,
            total=len(datasets)
        )
        
    except Exception as e:
        logger.error(f"Error listing datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list datasets: {str(e)}")


@router.get("/datasets/{dataset_id}")
async def get_dataset_metadata(
    dataset_id: str,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Get metadata for a specific dataset."""
    try:
        manager = get_training_manager()
        metadata = manager._load_dataset_metadata(dataset_id)
        
        if not metadata:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        return metadata.to_dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dataset metadata: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get dataset metadata: {str(e)}")


@router.post("/datasets/{dataset_id}/upload", response_model=UploadDatasetResponse)
async def upload_dataset_data(
    dataset_id: str,
    request: UploadDatasetRequest,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Upload training data to a dataset."""
    try:
        manager = get_training_manager()
        
        version_id = manager.upload_dataset(
            dataset_id=dataset_id,
            data=request.data,
            format=request.format,
            version_description=request.version_description,
            created_by=current_user.get("user_id", "unknown")
        )
        
        # Get validation report
        examples = manager.get_dataset(dataset_id, version_id)
        validation_report = manager.validate_dataset(examples)
        
        logger.info(f"Uploaded {len(request.data)} examples to dataset {dataset_id}, version {version_id}")
        
        return UploadDatasetResponse(
            version_id=version_id,
            validation_report=validation_report.to_dict(),
            message=f"Uploaded {len(request.data)} examples successfully"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error uploading dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload dataset: {str(e)}")


@router.post("/datasets/{dataset_id}/upload-file")
async def upload_dataset_file(
    dataset_id: str,
    file: UploadFile = File(...),
    format: DataFormat = Form(...),
    version_description: str = Form("File upload"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Upload training data from a file."""
    try:
        manager = get_training_manager()
        
        # Read file content
        content = await file.read()
        
        # Import dataset
        version_id = manager.upload_dataset(
            dataset_id=dataset_id,
            data=content,
            format=format,
            version_description=version_description,
            created_by=current_user.get("user_id", "unknown")
        )
        
        # Get validation report
        examples = manager.get_dataset(dataset_id, version_id)
        validation_report = manager.validate_dataset(examples)
        
        logger.info(f"Uploaded file {file.filename} to dataset {dataset_id}, version {version_id}")
        
        return UploadDatasetResponse(
            version_id=version_id,
            validation_report=validation_report.to_dict(),
            message=f"File '{file.filename}' uploaded successfully"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@router.get("/datasets/{dataset_id}/data")
async def get_dataset_data(
    dataset_id: str,
    version: Optional[str] = Query(None, description="Specific version"),
    limit: Optional[int] = Query(None, description="Limit number of examples"),
    offset: Optional[int] = Query(0, description="Offset for pagination"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Get training data from a dataset."""
    try:
        manager = get_training_manager()
        examples = manager.get_dataset(dataset_id, version)
        
        # Apply pagination
        if offset:
            examples = examples[offset:]
        if limit:
            examples = examples[:limit]
        
        # Convert to dictionaries
        data = [manager._example_to_dict(ex) for ex in examples]
        
        return {
            "examples": data,
            "total": len(data),
            "dataset_id": dataset_id,
            "version": version
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting dataset data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get dataset data: {str(e)}")


@router.post("/datasets/{dataset_id}/validate", response_model=ValidationResponse)
async def validate_dataset(
    dataset_id: str,
    version: Optional[str] = Query(None, description="Specific version"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Validate a training dataset."""
    try:
        manager = get_training_manager()
        examples = manager.get_dataset(dataset_id, version)
        
        validation_report = manager.validate_dataset(examples)
        quality_metrics = manager.assess_quality(examples)
        
        return ValidationResponse(
            validation_report=validation_report.to_dict(),
            quality_metrics=quality_metrics.to_dict()
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error validating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to validate dataset: {str(e)}")


@router.post("/datasets/{dataset_id}/enhance")
async def enhance_dataset(
    dataset_id: str,
    request: EnhanceDatasetRequest,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Enhance a training dataset."""
    try:
        manager = get_training_manager()
        examples = manager.get_dataset(dataset_id, request.version)
        
        enhanced_examples = manager.enhance_dataset(examples)
        
        if request.create_new_version:
            # Create new version with enhanced data
            version_id = manager.upload_dataset(
                dataset_id=dataset_id,
                data=[manager._example_to_dict(ex) for ex in enhanced_examples],
                format=DataFormat.JSON,
                version_description="Enhanced dataset",
                created_by=current_user.get("user_id", "unknown")
            )
            
            return {
                "message": "Dataset enhanced successfully",
                "version_id": version_id,
                "original_count": len(examples),
                "enhanced_count": len(enhanced_examples)
            }
        else:
            # Return enhanced data without saving
            return {
                "message": "Dataset enhancement preview",
                "enhanced_examples": [manager._example_to_dict(ex) for ex in enhanced_examples],
                "original_count": len(examples),
                "enhanced_count": len(enhanced_examples)
            }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error enhancing dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to enhance dataset: {str(e)}")


@router.post("/datasets/{dataset_id}/convert")
async def convert_dataset_format(
    dataset_id: str,
    request: ConvertFormatRequest,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Convert dataset to different format."""
    try:
        manager = get_training_manager()
        examples = manager.get_dataset(dataset_id, request.version)
        
        converted_data = manager.convert_format(examples, request.target_format)
        
        # Determine content type and filename
        content_type = "application/json"
        filename = f"dataset_{dataset_id}.json"
        
        if request.target_format == DataFormat.CSV:
            content_type = "text/csv"
            filename = f"dataset_{dataset_id}.csv"
        elif request.target_format == DataFormat.JSONL:
            content_type = "application/jsonl"
            filename = f"dataset_{dataset_id}.jsonl"
        elif request.target_format == DataFormat.PICKLE:
            content_type = "application/octet-stream"
            filename = f"dataset_{dataset_id}.pkl"
        
        # Convert to bytes if needed
        if isinstance(converted_data, str):
            content = converted_data.encode('utf-8')
        elif isinstance(converted_data, bytes):
            content = converted_data
        else:
            content = json.dumps(converted_data, indent=2).encode('utf-8')
        
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error converting dataset format: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to convert dataset format: {str(e)}")


@router.get("/datasets/{dataset_id}/export")
async def export_dataset(
    dataset_id: str,
    format: DataFormat = Query(DataFormat.JSON, description="Export format"),
    version: Optional[str] = Query(None, description="Specific version"),
    include_metadata: bool = Query(True, description="Include metadata"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Export a training dataset."""
    try:
        manager = get_training_manager()
        
        exported_data = manager.export_dataset(
            dataset_id=dataset_id,
            format=format,
            version=version,
            include_metadata=include_metadata
        )
        
        # Determine content type and filename
        content_type = "application/json"
        filename = f"export_{dataset_id}.json"
        
        if format == DataFormat.CSV:
            content_type = "text/csv"
            filename = f"export_{dataset_id}.csv"
        elif format == DataFormat.JSONL:
            content_type = "application/jsonl"
            filename = f"export_{dataset_id}.jsonl"
        elif format == DataFormat.PICKLE:
            content_type = "application/octet-stream"
            filename = f"export_{dataset_id}.pkl"
        
        return Response(
            content=exported_data,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to export dataset: {str(e)}")


@router.post("/datasets/import")
async def import_dataset(
    file: UploadFile = File(...),
    format: DataFormat = Form(...),
    name: str = Form(...),
    description: str = Form("Imported dataset"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Import a training dataset from file."""
    try:
        manager = get_training_manager()
        
        # Read file content
        content = await file.read()
        
        # Import dataset
        dataset_id = manager.import_dataset(
            data=content,
            format=format,
            dataset_name=name,
            created_by=current_user.get("user_id", "unknown"),
            description=description
        )
        
        logger.info(f"Imported dataset {dataset_id} from file {file.filename}")
        
        return {
            "dataset_id": dataset_id,
            "message": f"Dataset '{name}' imported successfully from '{file.filename}'"
        }
        
    except Exception as e:
        logger.error(f"Error importing dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to import dataset: {str(e)}")


@router.get("/datasets/{dataset_id}/versions", response_model=VersionListResponse)
async def list_dataset_versions(
    dataset_id: str,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """List all versions of a dataset."""
    try:
        manager = get_training_manager()
        versions = manager.list_versions(dataset_id)
        
        version_data = [version.to_dict() for version in versions]
        
        return VersionListResponse(
            versions=version_data,
            total=len(version_data)
        )
        
    except Exception as e:
        logger.error(f"Error listing dataset versions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list dataset versions: {str(e)}")


@router.post("/datasets/{dataset_id}/versions")
async def create_dataset_version(
    dataset_id: str,
    request: CreateVersionRequest,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:write"))
):
    """Create a new version based on an existing version."""
    try:
        manager = get_training_manager()
        
        version_id = manager.create_version_from_existing(
            dataset_id=dataset_id,
            source_version=request.source_version,
            description=request.description,
            modifications=request.modifications,
            created_by=current_user.get("user_id", "unknown")
        )
        
        logger.info(f"Created version {version_id} for dataset {dataset_id}")
        
        return {
            "version_id": version_id,
            "message": f"Version created successfully from {request.source_version}"
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating dataset version: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create dataset version: {str(e)}")


async def _legacy_delete_dataset(
    dataset_id: str,
    current_user: Dict[str, Any] = Depends(require_permission("training_data:delete"))
):
    """Delete a training dataset and all its versions."""
    try:
        manager = get_training_manager()
        
        # Check if dataset exists
        metadata = manager._load_dataset_metadata(dataset_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        # Delete dataset files
        import shutil
        
        # Delete metadata
        metadata_path = manager.metadata_dir / f"{dataset_id}.json"
        if metadata_path.exists():
            metadata_path.unlink()
        
        # Delete dataset directory
        dataset_dir = manager.datasets_dir / dataset_id
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)
        
        # Delete versions directory
        versions_dir = manager.versions_dir / dataset_id
        if versions_dir.exists():
            shutil.rmtree(versions_dir)
        
        logger.info(f"Deleted dataset {dataset_id}")
        
        return {"message": f"Dataset {dataset_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete dataset: {str(e)}")


@router.get("/datasets/{dataset_id}/statistics")
async def get_dataset_statistics(
    dataset_id: str,
    version: Optional[str] = Query(None, description="Specific version"),
    current_user: Dict[str, Any] = Depends(require_permission("training_data:read"))
):
    """Get statistical information about a dataset."""
    try:
        manager = get_training_manager()
        examples = manager.get_dataset(dataset_id, version)
        
        validation_report = manager.validate_dataset(examples)
        quality_metrics = manager.assess_quality(examples)
        
        return {
            "dataset_id": dataset_id,
            "version": version,
            "statistics": validation_report.statistics,
            "quality_metrics": quality_metrics.to_dict(),
            "validation_summary": {
                "total_examples": validation_report.total_examples,
                "valid_examples": validation_report.valid_examples,
                "invalid_examples": validation_report.invalid_examples,
                "quality_score": validation_report.quality_score,
                "issue_count": len(validation_report.issues)
            }
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting dataset statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get dataset statistics: {str(e)}")


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for training data management system."""
    try:
        manager = get_training_manager()
        
        # Check if directories exist and are writable
        directories_ok = all([
            manager.data_dir.exists(),
            manager.datasets_dir.exists(),
            manager.versions_dir.exists(),
            manager.metadata_dir.exists()
        ])
        
        return {
            "status": "healthy" if directories_ok else "degraded",
            "directories_ok": directories_ok,
            "data_dir": str(manager.data_dir),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
