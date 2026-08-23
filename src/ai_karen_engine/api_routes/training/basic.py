"""
API routes for Basic Training Mode functionality.

This module provides REST API endpoints for simplified training interfaces,
automatic parameter selection, progress monitoring, and system reset capabilities.
"""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks

from pydantic import BaseModel, Field

from ai_karen_engine.learning.basic_training_mode import (
    BasicTrainingMode,
    BasicTrainingDifficulty,
)
from ai_karen_engine.services.training.training_interface import (
    TrainingType,
    TrainingStatus,
)
from ai_karen_engine.learning.training_data_manager import TrainingDataManager
from ai_karen_engine.inference.huggingface_service import (
    get_enhanced_huggingface_service,
)
from ai_karen_engine.core.model_runtime.management.system_model_manager import SystemModelManager

logger = logging.getLogger(__name__)
router = APIRouter()

# Global instance (will be initialized by the application)
_basic_training_mode: Optional[BasicTrainingMode] = None


def get_basic_training_mode() -> BasicTrainingMode:
    """Get the global BasicTrainingMode instance."""
    global _basic_training_mode
    if _basic_training_mode is None:
        # Initialize with dependencies
        from ai_karen_engine.services.training.training_interface import (
            FlexibleTrainingInterface,
        )

        enhanced_hf_service = get_enhanced_huggingface_service()
        training_data_manager = TrainingDataManager()
        system_model_manager = SystemModelManager()
        training_interface = FlexibleTrainingInterface(
            enhanced_hf_service, training_data_manager, system_model_manager
        )

        _basic_training_mode = BasicTrainingMode(
            training_interface,
            training_data_manager,
            system_model_manager,
            enhanced_hf_service,
        )

    return _basic_training_mode


# Request/Response Models


class BasicTrainingPresetResponse(BaseModel):
    """Response model for training presets."""

    name: str
    description: str
    difficulty: BasicTrainingDifficulty
    training_type: TrainingType
    num_epochs: int
    learning_rate: float
    batch_size: int
    max_length: int
    warmup_ratio: float
    use_mixed_precision: bool
    gradient_checkpointing: bool
    recommended_for: List[str]
    estimated_time: str
    memory_requirements_gb: float


class StartBasicTrainingRequest(BaseModel):
    """Request model for starting basic training."""

    model_id: str = Field(..., description="HuggingFace model ID")
    dataset_id: str = Field(..., description="Training dataset ID")
    preset_name: Optional[str] = Field(None, description="Training preset name")
    custom_description: Optional[str] = Field(
        None, description="Custom training description"
    )


class TrainingProgressResponse(BaseModel):
    """Response model for training progress."""

    job_id: str
    model_name: str
    status: str
    progress_percentage: float
    current_step: int
    total_steps: int
    current_epoch: int
    total_epochs: int
    elapsed_time: str
    estimated_remaining: str
    current_loss: Optional[float] = None
    best_loss: Optional[float] = None
    learning_rate: Optional[float] = None
    memory_usage_gb: Optional[float] = None
    gpu_utilization: Optional[float] = None
    status_message: str
    warnings: List[str]
    recommendations: List[str]


class TrainingResultResponse(BaseModel):
    """Response model for training results."""

    job_id: str
    model_name: str
    success: bool
    training_time: str
    final_loss: Optional[float]
    improvement_percentage: Optional[float]
    model_path: Optional[str]
    performance_summary: str
    recommendations: List[str]
    warnings: List[str]
    next_steps: List[str]


class SystemBackupResponse(BaseModel):
    """Response model for system backups."""

    backup_id: str
    created_at: datetime
    description: str
    backup_path: str
    size_mb: float


class CreateBackupRequest(BaseModel):
    """Request model for creating system backup."""

    description: str = Field("Manual backup", description="Backup description")


class RestoreBackupRequest(BaseModel):
    """Request model for restoring system backup."""

    backup_id: str = Field(..., description="Backup ID to restore")


class ResetSystemRequest(BaseModel):
    """Request model for system reset."""

    preserve_user_data: bool = Field(True, description="Whether to preserve user data")


# Training Preset Endpoints


@router.get(
    "/api/basic-training/presets", response_model=List[BasicTrainingPresetResponse]
)
async def get_recommended_presets():
    """Get training presets recommended for current hardware."""
    try:
        basic_training = get_basic_training_mode()
        presets = await basic_training.get_recommended_presets()

        return [
            BasicTrainingPresetResponse(
                name=preset.name,
                description=preset.description,
                difficulty=preset.difficulty,
                training_type=preset.training_type,
                num_epochs=preset.num_epochs,
                learning_rate=preset.learning_rate,
                batch_size=preset.batch_size,
                max_length=preset.max_length,
                warmup_ratio=preset.warmup_ratio,
                use_mixed_precision=preset.use_mixed_precision,
                gradient_checkpointing=preset.gradient_checkpointing,
                recommended_for=preset.recommended_for,
                estimated_time=preset.estimated_time,
                memory_requirements_gb=preset.memory_requirements_gb,
            )
            for preset in presets
        ]

    except Exception as e:
        logger.error(f"Failed to get recommended presets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/basic-training/presets/{model_id:path}",
    response_model=BasicTrainingPresetResponse,
)
async def get_preset_for_model(model_id: str):
    """Get the best preset for a specific model."""
    try:
        basic_training = get_basic_training_mode()
        preset = await basic_training.get_preset_for_model(model_id)

        if not preset:
            raise HTTPException(
                status_code=404, detail="No suitable preset found for this model"
            )

        return BasicTrainingPresetResponse(
            name=preset.name,
            description=preset.description,
            difficulty=preset.difficulty,
            training_type=preset.training_type,
            num_epochs=preset.num_epochs,
            learning_rate=preset.learning_rate,
            batch_size=preset.batch_size,
            max_length=preset.max_length,
            warmup_ratio=preset.warmup_ratio,
            use_mixed_precision=preset.use_mixed_precision,
            gradient_checkpointing=preset.gradient_checkpointing,
            recommended_for=preset.recommended_for,
            estimated_time=preset.estimated_time,
            memory_requirements_gb=preset.memory_requirements_gb,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get preset for model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Training Job Endpoints


@router.post("/api/basic-training/start")
async def start_basic_training(
    request: StartBasicTrainingRequest, background_tasks: BackgroundTasks
):
    """Start basic training with automatic parameter selection."""
    try:
        basic_training = get_basic_training_mode()

        job = await basic_training.start_basic_training(
            model_id=request.model_id,
            dataset_id=request.dataset_id,
            preset_name=request.preset_name,
            custom_description=request.custom_description,
        )

        return {
            "job_id": job.job_id,
            "model_id": job.model_id,
            "status": job.status.value,
            "created_at": job.created_at,
            "message": "Basic training started successfully",
        }

    except Exception as e:
        logger.error(f"Failed to start basic training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/basic-training/progress/{job_id}", response_model=TrainingProgressResponse
)
async def get_training_progress(job_id: str):
    """Get user-friendly training progress."""
    try:
        basic_training = get_basic_training_mode()
        progress = basic_training.get_training_progress(job_id)

        if not progress:
            raise HTTPException(status_code=404, detail="Training job not found")

        return TrainingProgressResponse(
            job_id=progress.job_id,
            model_name=progress.model_name,
            status=progress.status,
            progress_percentage=progress.progress_percentage,
            current_step=progress.current_step,
            total_steps=progress.total_steps,
            current_epoch=progress.current_epoch,
            total_epochs=progress.total_epochs,
            elapsed_time=progress.elapsed_time,
            estimated_remaining=progress.estimated_remaining,
            current_loss=progress.current_loss,
            best_loss=progress.best_loss,
            learning_rate=progress.learning_rate,
            memory_usage_gb=progress.memory_usage_gb,
            gpu_utilization=progress.gpu_utilization,
            status_message=progress.status_message,
            warnings=progress.warnings,
            recommendations=progress.recommendations,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get training progress for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/basic-training/result/{job_id}", response_model=TrainingResultResponse
)
async def get_training_result(job_id: str):
    """Get plain-language training result summary."""
    try:
        basic_training = get_basic_training_mode()
        result = basic_training.get_training_result(job_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Training result not found or training not completed",
            )

        return TrainingResultResponse(
            job_id=result.job_id,
            model_name=result.model_name,
            success=result.success,
            training_time=result.training_time,
            final_loss=result.final_loss,
            improvement_percentage=result.improvement_percentage,
            model_path=result.model_path,
            performance_summary=result.performance_summary,
            recommendations=result.recommendations,
            warnings=result.warnings,
            next_steps=result.next_steps,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get training result for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/basic-training/cancel/{job_id}")
async def cancel_training(job_id: str):
    """Cancel a training job."""
    try:
        basic_training = get_basic_training_mode()
        success = basic_training.cancel_training(job_id)

        if not success:
            raise HTTPException(
                status_code=404, detail="Training job not found or cannot be cancelled"
            )

        return {"message": f"Training job {job_id} cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel training job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# System Reset Endpoints


@router.post("/api/basic-training/backup", response_model=SystemBackupResponse)
async def create_system_backup(request: CreateBackupRequest):
    """Create a complete system configuration backup."""
    try:
        basic_training = get_basic_training_mode()
        backup = basic_training.create_system_backup(request.description)

        return SystemBackupResponse(
            backup_id=backup.backup_id,
            created_at=backup.created_at,
            description=backup.description,
            backup_path=backup.backup_path,
            size_mb=backup.size_mb,
        )

    except Exception as e:
        logger.error(f"Failed to create system backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/basic-training/restore")
async def restore_system_backup(request: RestoreBackupRequest):
    """Restore system configuration from backup."""
    try:
        basic_training = get_basic_training_mode()
        success = basic_training.restore_system_backup(request.backup_id)

        if not success:
            raise HTTPException(
                status_code=404, detail="Backup not found or restore failed"
            )

        return {
            "message": f"System restored from backup {request.backup_id} successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore system backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/basic-training/reset")
async def reset_to_factory_defaults(request: ResetSystemRequest):
    """Reset system to factory defaults."""
    try:
        basic_training = get_basic_training_mode()
        success = basic_training.reset_to_factory_defaults(request.preserve_user_data)

        if not success:
            raise HTTPException(
                status_code=500, detail="Failed to reset system to factory defaults"
            )

        return {
            "message": "System reset to factory defaults successfully",
            "preserve_user_data": request.preserve_user_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset system to factory defaults: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/basic-training/backups", response_model=List[SystemBackupResponse])
async def list_system_backups():
    """List all available system backups."""
    try:
        basic_training = get_basic_training_mode()
        backups = basic_training.list_system_backups()

        return [
            SystemBackupResponse(
                backup_id=backup.backup_id,
                created_at=backup.created_at,
                description=backup.description,
                backup_path=backup.backup_path,
                size_mb=backup.size_mb,
            )
            for backup in backups
        ]

    except Exception as e:
        logger.error(f"Failed to list system backups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/basic-training/backup/{backup_id}")
async def delete_system_backup(backup_id: str):
    """Delete a system backup."""
    try:
        basic_training = get_basic_training_mode()
        success = basic_training.delete_system_backup(backup_id)

        if not success:
            raise HTTPException(
                status_code=404, detail="Backup not found or delete failed"
            )

        return {"message": f"Backup {backup_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete system backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Health and Status Endpoints


@router.get("/api/basic-training/status")
async def get_basic_training_status():
    """Get basic training system status."""
    try:
        basic_training = get_basic_training_mode()

        # Get hardware info
        from ai_karen_engine.services.training.training_interface import HardwareConstraints

        hardware = HardwareConstraints.detect_current()

        # Get active jobs count
        active_jobs = len(
            [
                job
                for job in basic_training.training_interface.active_jobs.values()
                if job.status
                in [
                    TrainingStatus.PENDING,
                    TrainingStatus.TRAINING,
                    TrainingStatus.VALIDATING,
                ]
            ]
        )
        recommended_presets = await basic_training.get_recommended_presets()
        system_backups = basic_training.list_system_backups()

        return {
            "status": "operational",
            "hardware": {
                "available_memory_gb": hardware.available_memory_gb,
                "available_gpu_memory_gb": hardware.available_gpu_memory_gb,
                "gpu_count": hardware.gpu_count,
                "cpu_cores": hardware.cpu_cores,
                "supports_mixed_precision": hardware.supports_mixed_precision,
            },
            "active_training_jobs": active_jobs,
            "available_presets": len(recommended_presets),
            "system_backups": len(system_backups),
        }

    except Exception as e:
        logger.error(f"Failed to get basic training status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

