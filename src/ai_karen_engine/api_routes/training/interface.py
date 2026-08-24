"""
API routes for the Flexible Model Training Interface.

This module provides REST API endpoints for model compatibility checking,
training environment setup, and training job management with different
complexity levels and hardware validation.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
try:
    from pydantic import BaseModel, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field

from ai_karen_engine.services.training.training_interface import (
    FlexibleTrainingInterface,
    TrainingMode,
    TrainingType,
    TrainingStatus,
    BasicTrainingConfig,
    AdvancedTrainingConfig,
    ModelCompatibility,
    TrainingJob,
    HardwareConstraints
)
from ai_karen_engine.core.model_runtime.huggingface_service import EnhancedHuggingFaceService
from ai_karen_engine.learning.training_data_manager import TrainingDataManager
from ai_karen_engine.core.model_runtime.management.system_model_manager import SystemModelManager

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/training", tags=["training"])

# Dependency injection
def get_training_interface() -> FlexibleTrainingInterface:
    """Get training interface instance."""
    # In a real implementation, this would be properly injected
    enhanced_hf_service = HuggingFaceService()
    training_data_manager = TrainingDataManager()
    system_model_manager = SystemModelManager()
    
    return FlexibleTrainingInterface(
        enhanced_hf_service=enhanced_hf_service,
        training_data_manager=training_data_manager,
        system_model_manager=system_model_manager
    )

# Request/Response Models

class CompatibilityCheckRequest(BaseModel):
    """Request model for compatibility checking."""
    model_id: str = Field(..., description="HuggingFace model ID")
    training_type: TrainingType = Field(..., description="Type of training operation")

class CompatibilityCheckResponse(BaseModel):
    """Response model for compatibility checking."""
    model_id: str
    is_compatible: bool
    supports_fine_tuning: bool
    supports_lora: bool
    supports_full_training: bool
    required_memory_gb: float
    required_gpu_memory_gb: float
    recommended_batch_size: int
    training_frameworks: List[str]
    compatibility_issues: List[str]
    recommendations: List[str]
    estimated_training_time: Optional[str]

class BasicTrainingRequest(BaseModel):
    """Request model for basic training."""
    model_id: str = Field(..., description="HuggingFace model ID")
    dataset_id: str = Field(..., description="Training dataset ID")
    training_type: TrainingType = Field(..., description="Type of training operation")
    num_epochs: int = Field(3, ge=1, le=20, description="Number of training epochs")
    learning_rate: float = Field(2e-5, gt=0, le=1e-2, description="Learning rate")
    batch_size: int = Field(8, ge=1, le=128, description="Batch size")
    max_length: int = Field(512, ge=64, le=4096, description="Maximum sequence length")
    warmup_steps: int = Field(100, ge=0, description="Warmup steps")
    save_steps: int = Field(500, ge=100, description="Save checkpoint every N steps")
    eval_steps: int = Field(500, ge=100, description="Evaluate every N steps")
    output_dir: Optional[str] = Field(None, description="Output directory")
    use_mixed_precision: bool = Field(True, description="Use mixed precision training")
    gradient_checkpointing: bool = Field(True, description="Use gradient checkpointing")

class AdvancedTrainingRequest(BaseModel):
    """Request model for advanced training."""
    model_id: str = Field(..., description="HuggingFace model ID")
    dataset_id: str = Field(..., description="Training dataset ID")
    training_type: TrainingType = Field(..., description="Type of training operation")
    
    # Learning parameters
    learning_rate: float = Field(2e-5, gt=0, le=1e-2)
    weight_decay: float = Field(0.01, ge=0, le=1.0)
    adam_beta1: float = Field(0.9, ge=0, le=1.0)
    adam_beta2: float = Field(0.999, ge=0, le=1.0)
    adam_epsilon: float = Field(1e-8, gt=0)
    max_grad_norm: float = Field(1.0, gt=0)
    
    # Training schedule
    num_epochs: int = Field(3, ge=1, le=50)
    warmup_steps: int = Field(100, ge=0)
    warmup_ratio: float = Field(0.1, ge=0, le=1.0)
    lr_scheduler_type: str = Field("linear", pattern="^(linear|cosine|polynomial|constant)$")
    
    # Batch and sequence settings
    per_device_train_batch_size: int = Field(8, ge=1, le=128)
    per_device_eval_batch_size: int = Field(8, ge=1, le=128)
    gradient_accumulation_steps: int = Field(1, ge=1, le=64)
    max_length: int = Field(512, ge=64, le=8192)
    
    # Optimization settings
    fp16: bool = Field(False)
    bf16: bool = Field(False)
    gradient_checkpointing: bool = Field(True)
    dataloader_num_workers: int = Field(0, ge=0, le=16)
    
    # Logging and saving
    logging_steps: int = Field(10, ge=1)
    save_steps: int = Field(500, ge=100)
    eval_steps: int = Field(500, ge=100)
    save_total_limit: int = Field(3, ge=1, le=10)
    
    # LoRA specific settings
    lora_r: int = Field(16, ge=1, le=256)
    lora_alpha: int = Field(32, ge=1, le=512)
    lora_dropout: float = Field(0.1, ge=0, le=0.5)
    lora_target_modules: List[str] = Field(default=["q_proj", "v_proj"])
    
    # Output settings
    output_dir: Optional[str] = None
    run_name: Optional[str] = None
    
    # Custom parameters
    custom_parameters: Dict[str, Any] = Field(default_factory=dict)

class TrainingJobResponse(BaseModel):
    """Response model for training jobs."""
    job_id: str
    model_id: str
    training_type: TrainingType
    training_mode: TrainingMode
    status: TrainingStatus
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    progress: float
    current_epoch: int
    total_epochs: int
    current_step: int
    total_steps: int
    loss: Optional[float]
    eval_loss: Optional[float]
    learning_rate: Optional[float]
    error_message: Optional[str]
    output_dir: Optional[str]
    model_path: Optional[str]
    logs: List[str]
    metrics: Dict[str, Any]

class HardwareConstraintsResponse(BaseModel):
    """Response model for hardware constraints."""
    available_memory_gb: float
    available_gpu_memory_gb: float
    gpu_count: int
    cpu_cores: int
    supports_mixed_precision: bool
    supports_gradient_checkpointing: bool
    max_batch_size: Optional[int]
    recommended_precision: str

class TrainableModelsResponse(BaseModel):
    """Response model for trainable models list."""
    models: List[Dict[str, Any]]
    total_count: int

# API Endpoints

@router.post("/compatibility/check", response_model=CompatibilityCheckResponse)
async def check_model_compatibility(
    request: CompatibilityCheckRequest,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Check if a model is compatible for training."""
    try:
        compatibility = await training_interface.check_model_compatibility(
            request.model_id, request.training_type
        )
        
        return CompatibilityCheckResponse(
            model_id=compatibility.model_id,
            is_compatible=compatibility.is_compatible,
            supports_fine_tuning=compatibility.supports_fine_tuning,
            supports_lora=compatibility.supports_lora,
            supports_full_training=compatibility.supports_full_training,
            required_memory_gb=compatibility.required_memory_gb,
            required_gpu_memory_gb=compatibility.required_gpu_memory_gb,
            recommended_batch_size=compatibility.recommended_batch_size,
            training_frameworks=compatibility.training_frameworks,
            compatibility_issues=compatibility.compatibility_issues,
            recommendations=compatibility.recommendations,
            estimated_training_time=compatibility.estimated_training_time
        )
        
    except Exception as e:
        logger.error(f"Error checking model compatibility: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/jobs/basic", response_model=TrainingJobResponse)
async def create_basic_training_job(
    request: BasicTrainingRequest,
    background_tasks: BackgroundTasks,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Create a basic training job with preset configurations."""
    try:
        config = BasicTrainingConfig(
            model_id=request.model_id,
            dataset_id=request.dataset_id,
            training_type=request.training_type,
            num_epochs=request.num_epochs,
            learning_rate=request.learning_rate,
            batch_size=request.batch_size,
            max_length=request.max_length,
            warmup_steps=request.warmup_steps,
            save_steps=request.save_steps,
            eval_steps=request.eval_steps,
            output_dir=request.output_dir,
            use_mixed_precision=request.use_mixed_precision,
            gradient_checkpointing=request.gradient_checkpointing
        )
        
        job = await training_interface.create_basic_training_job(config)
        
        return _job_to_response(job)
        
    except Exception as e:
        logger.error(f"Error creating basic training job: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/jobs/advanced", response_model=TrainingJobResponse)
async def create_advanced_training_job(
    request: AdvancedTrainingRequest,
    background_tasks: BackgroundTasks,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Create an advanced training job with full configuration control."""
    try:
        config = AdvancedTrainingConfig(
            model_id=request.model_id,
            dataset_id=request.dataset_id,
            training_type=request.training_type,
            learning_rate=request.learning_rate,
            weight_decay=request.weight_decay,
            adam_beta1=request.adam_beta1,
            adam_beta2=request.adam_beta2,
            adam_epsilon=request.adam_epsilon,
            max_grad_norm=request.max_grad_norm,
            num_epochs=request.num_epochs,
            warmup_steps=request.warmup_steps,
            warmup_ratio=request.warmup_ratio,
            lr_scheduler_type=request.lr_scheduler_type,
            per_device_train_batch_size=request.per_device_train_batch_size,
            per_device_eval_batch_size=request.per_device_eval_batch_size,
            gradient_accumulation_steps=request.gradient_accumulation_steps,
            max_length=request.max_length,
            fp16=request.fp16,
            bf16=request.bf16,
            gradient_checkpointing=request.gradient_checkpointing,
            dataloader_num_workers=request.dataloader_num_workers,
            logging_steps=request.logging_steps,
            save_steps=request.save_steps,
            eval_steps=request.eval_steps,
            save_total_limit=request.save_total_limit,
            lora_r=request.lora_r,
            lora_alpha=request.lora_alpha,
            lora_dropout=request.lora_dropout,
            lora_target_modules=request.lora_target_modules,
            output_dir=request.output_dir,
            run_name=request.run_name,
            custom_parameters=request.custom_parameters
        )
        
        job = await training_interface.create_advanced_training_job(config)
        
        return _job_to_response(job)
        
    except Exception as e:
        logger.error(f"Error creating advanced training job: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/jobs/{job_id}/start")
async def start_training_job(
    job_id: str,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Start a training job."""
    try:
        success = await training_interface.start_training_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to start training job")
        
        return {"message": "Training job started successfully", "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Error starting training job {job_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/jobs/{job_id}/cancel")
async def cancel_training_job(
    job_id: str,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Cancel a training job."""
    try:
        success = await training_interface.cancel_training_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to cancel training job")
        
        return {"message": "Training job cancelled successfully", "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Error cancelling training job {job_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/jobs/{job_id}", response_model=TrainingJobResponse)
async def get_training_job(
    job_id: str,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Get training job details."""
    try:
        job = training_interface.get_training_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Training job not found")
        
        return _job_to_response(job)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting training job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jobs", response_model=List[TrainingJobResponse])
async def list_training_jobs(
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """List all training jobs."""
    try:
        jobs = training_interface.list_training_jobs()
        return [_job_to_response(job) for job in jobs]
        
    except Exception as e:
        logger.error(f"Error listing training jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/hardware", response_model=HardwareConstraintsResponse)
async def get_hardware_constraints(
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Get current hardware constraints."""
    try:
        constraints = training_interface.get_hardware_constraints()
        
        return HardwareConstraintsResponse(
            available_memory_gb=constraints.available_memory_gb,
            available_gpu_memory_gb=constraints.available_gpu_memory_gb,
            gpu_count=constraints.gpu_count,
            cpu_cores=constraints.cpu_cores,
            supports_mixed_precision=constraints.supports_mixed_precision,
            supports_gradient_checkpointing=constraints.supports_gradient_checkpointing,
            max_batch_size=constraints.max_batch_size,
            recommended_precision=constraints.recommended_precision
        )
        
    except Exception as e:
        logger.error(f"Error getting hardware constraints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/trainable", response_model=TrainableModelsResponse)
async def get_trainable_models(
    supports_fine_tuning: Optional[bool] = None,
    supports_lora: Optional[bool] = None,
    supports_full_training: Optional[bool] = None,
    min_parameters: Optional[str] = None,
    max_parameters: Optional[str] = None,
    training_interface: FlexibleTrainingInterface = Depends(get_training_interface)
):
    """Get list of trainable models with optional filtering."""
    try:
        filters = {}
        if supports_fine_tuning is not None:
            filters["supports_fine_tuning"] = supports_fine_tuning
        if supports_lora is not None:
            filters["supports_lora"] = supports_lora
        if supports_full_training is not None:
            filters["supports_full_training"] = supports_full_training
        if min_parameters:
            filters["min_parameters"] = min_parameters
        if max_parameters:
            filters["max_parameters"] = max_parameters
        
        models = await training_interface.get_trainable_models(filters)
        
        model_dicts = []
        for model in models:
            model_dict = {
                "id": model.id,
                "name": model.name,
                "family": model.family,
                "parameters": model.parameters,
                "supports_fine_tuning": getattr(model, "supports_fine_tuning", False),
                "supports_lora": getattr(model, "supports_lora", False),
                "supports_full_training": getattr(model, "supports_full_training", False),
                "training_frameworks": getattr(model, "training_frameworks", []),
                "training_complexity": getattr(model, "training_complexity", "unknown"),
                "tags": model.tags,
                "downloads": model.downloads,
                "likes": model.likes
            }
            model_dicts.append(model_dict)
        
        return TrainableModelsResponse(
            models=model_dicts,
            total_count=len(model_dicts)
        )
        
    except Exception as e:
        logger.error(f"Error getting trainable models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper Functions

def _job_to_response(job: TrainingJob) -> TrainingJobResponse:
    """Convert TrainingJob to response model."""
    return TrainingJobResponse(
        job_id=job.job_id,
        model_id=job.model_id,
        training_type=job.training_type,
        training_mode=job.training_mode,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        progress=job.progress,
        current_epoch=job.current_epoch,
        total_epochs=job.total_epochs,
        current_step=job.current_step,
        total_steps=job.total_steps,
        loss=job.loss,
        eval_loss=job.eval_loss,
        learning_rate=job.learning_rate,
        error_message=job.error_message,
        output_dir=job.output_dir,
        model_path=job.model_path,
        logs=job.logs,
        metrics=job.metrics
    )

