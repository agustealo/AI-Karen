"""
Flexible Model Training Interface for the Response Core orchestrator.

This module implements a comprehensive training interface that provides model
compatibility checking, training environment setup, basic and advanced training
modes, and support for fine-tuning, continued pre-training, and task-specific
adaptation with hardware constraint validation.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil
import torch
from transformers import AutoConfig, AutoTokenizer, AutoModel

from ai_karen_engine.learning.training_data_manager import TrainingDataManager, TrainingExample
from ai_karen_engine.learning.autonomous_learner import AutonomousLearner, ValidationResult
from ai_karen_engine.core.model_runtime.huggingface_service import HuggingFaceService
from ai_karen_engine.core.model_runtime.management.system_model_manager import SystemModelManager

logger = logging.getLogger(__name__)


class TrainingMode(str, Enum):
    """Training mode complexity levels."""
    BASIC = "basic"
    ADVANCED = "advanced"
    EXPERT = "expert"


class TrainingType(str, Enum):
    """Types of training operations."""
    FINE_TUNING = "fine_tuning"
    CONTINUED_PRETRAINING = "continued_pretraining"
    TASK_SPECIFIC = "task_specific"
    LORA_ADAPTATION = "lora_adaptation"
    FULL_TRAINING = "full_training"


class TrainingStatus(str, Enum):
    """Training job status."""
    PENDING = "pending"
    VALIDATING = "validating"
    PREPARING = "preparing"
    TRAINING = "training"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class HardwareConstraints:
    """Hardware constraints for training."""
    available_memory_gb: float
    available_gpu_memory_gb: float
    gpu_count: int
    cpu_cores: int
    supports_mixed_precision: bool = False
    supports_gradient_checkpointing: bool = False
    max_batch_size: Optional[int] = None
    recommended_precision: str = "fp16"
    
    @classmethod
    def detect_current(cls) -> 'HardwareConstraints':
        """Detect current hardware constraints."""
        # Get system memory
        memory = psutil.virtual_memory()
        available_memory_gb = memory.available / (1024**3)
        
        # Get GPU information
        gpu_count = 0
        available_gpu_memory_gb = 0.0
        supports_mixed_precision = False
        
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            for i in range(gpu_count):
                props = torch.cuda.get_device_properties(i)
                gpu_memory_gb = props.total_memory / (1024**3)
                available_gpu_memory_gb = max(available_gpu_memory_gb, gpu_memory_gb)
                
                # Check for mixed precision support (Tensor Cores)
                if props.major >= 7:  # Volta and newer
                    supports_mixed_precision = True
        
        # Get CPU cores
        cpu_cores = psutil.cpu_count(logical=False) or 1
        
        return cls(
            available_memory_gb=available_memory_gb,
            available_gpu_memory_gb=available_gpu_memory_gb,
            gpu_count=gpu_count,
            cpu_cores=cpu_cores,
            supports_mixed_precision=supports_mixed_precision,
            supports_gradient_checkpointing=True,  # Most modern frameworks support this
            recommended_precision="fp16" if supports_mixed_precision else "fp32"
        )


@dataclass
class ModelCompatibility:
    """Model compatibility assessment for training."""
    model_id: str
    is_compatible: bool
    supports_fine_tuning: bool = False
    supports_lora: bool = False
    supports_full_training: bool = False
    required_memory_gb: float = 0.0
    required_gpu_memory_gb: float = 0.0
    recommended_batch_size: int = 1
    training_frameworks: List[str] = field(default_factory=list)
    compatibility_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    estimated_training_time: Optional[str] = None


@dataclass
class TrainingEnvironment:
    """Training environment configuration."""
    model_id: str
    training_type: TrainingType
    training_mode: TrainingMode
    output_dir: Path
    temp_dir: Path
    model_cache_dir: Path
    data_dir: Path
    checkpoint_dir: Path
    logs_dir: Path
    hardware_constraints: HardwareConstraints
    environment_ready: bool = False
    setup_errors: List[str] = field(default_factory=list)


@dataclass
class BasicTrainingConfig:
    """Basic training configuration with preset parameters."""
    model_id: str
    dataset_id: str
    training_type: TrainingType
    num_epochs: int = 3
    learning_rate: float = 2e-5
    batch_size: int = 8
    max_length: int = 512
    warmup_steps: int = 100
    save_steps: int = 500
    eval_steps: int = 500
    output_dir: Optional[str] = None
    use_mixed_precision: bool = True
    gradient_checkpointing: bool = True


@dataclass
class AdvancedTrainingConfig:
    """Advanced training configuration with full control."""
    model_id: str
    dataset_id: str
    training_type: TrainingType
    
    # Learning parameters
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    adam_beta1: float = 0.9
    adam_beta2: float = 0.999
    adam_epsilon: float = 1e-8
    max_grad_norm: float = 1.0
    
    # Training schedule
    num_epochs: int = 3
    warmup_steps: int = 100
    warmup_ratio: float = 0.1
    lr_scheduler_type: str = "linear"
    
    # Batch and sequence settings
    per_device_train_batch_size: int = 8
    per_device_eval_batch_size: int = 8
    gradient_accumulation_steps: int = 1
    max_length: int = 512
    
    # Optimization settings
    fp16: bool = False
    bf16: bool = False
    gradient_checkpointing: bool = True
    dataloader_num_workers: int = 0
    
    # Logging and saving
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 500
    save_total_limit: int = 3
    
    # LoRA specific settings (if applicable)
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.1
    lora_target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])
    
    # Output settings
    output_dir: Optional[str] = None
    run_name: Optional[str] = None
    
    # Custom settings
    custom_parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingJob:
    """Training job tracking."""
    job_id: str
    model_id: str
    training_type: TrainingType
    training_mode: TrainingMode
    status: TrainingStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    current_epoch: int = 0
    total_epochs: int = 0
    current_step: int = 0
    total_steps: int = 0
    loss: Optional[float] = None
    eval_loss: Optional[float] = None
    learning_rate: Optional[float] = None
    error_message: Optional[str] = None
    output_dir: Optional[str] = None
    model_path: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class ModelCompatibilityChecker:
    """Checks model compatibility for training operations."""
    
    def __init__(self, enhanced_hf_service: HuggingFaceService):
        self.enhanced_hf_service = enhanced_hf_service
        self.logger = logging.getLogger(__name__)
    
    async def check_compatibility(
        self, 
        model_id: str, 
        training_type: TrainingType,
        hardware_constraints: HardwareConstraints
    ) -> ModelCompatibility:
        """Check if a model is compatible for training."""
        try:
            # Get model information
            model_info = await self.enhanced_hf_service.get_model_info(model_id)
            if not model_info:
                return ModelCompatibility(
                    model_id=model_id,
                    is_compatible=False,
                    compatibility_issues=["Model not found or inaccessible"]
                )
            
            # Check if it's a trainable model
            if isinstance(model_info, TrainableModel):
                trainable_model = model_info
            else:
                # Convert to trainable model for analysis
                trainable_model = TrainableModel(**model_info.__dict__)
            
            compatibility = ModelCompatibility(model_id=model_id, is_compatible=True)
            
            # Check training type support
            if training_type == TrainingType.FINE_TUNING:
                compatibility.supports_fine_tuning = trainable_model.supports_fine_tuning
                if not compatibility.supports_fine_tuning:
                    compatibility.compatibility_issues.append("Model does not support fine-tuning")
            
            elif training_type == TrainingType.LORA_ADAPTATION:
                compatibility.supports_lora = trainable_model.supports_lora
                if not compatibility.supports_lora:
                    compatibility.compatibility_issues.append("Model does not support LoRA adaptation")
            
            elif training_type == TrainingType.FULL_TRAINING:
                compatibility.supports_full_training = trainable_model.supports_full_training
                if not compatibility.supports_full_training:
                    compatibility.compatibility_issues.append("Model does not support full training")
            
            # Estimate memory requirements
            compatibility.required_memory_gb = self._estimate_memory_requirements(
                trainable_model, training_type
            )
            compatibility.required_gpu_memory_gb = self._estimate_gpu_memory_requirements(
                trainable_model, training_type
            )
            
            # Check hardware constraints
            if compatibility.required_memory_gb > hardware_constraints.available_memory_gb:
                compatibility.compatibility_issues.append(
                    f"Insufficient system memory: {compatibility.required_memory_gb:.1f}GB required, "
                    f"{hardware_constraints.available_memory_gb:.1f}GB available"
                )
            
            if compatibility.required_gpu_memory_gb > hardware_constraints.available_gpu_memory_gb:
                compatibility.compatibility_issues.append(
                    f"Insufficient GPU memory: {compatibility.required_gpu_memory_gb:.1f}GB required, "
                    f"{hardware_constraints.available_gpu_memory_gb:.1f}GB available"
                )
            
            # Recommend batch size
            compatibility.recommended_batch_size = self._recommend_batch_size(
                trainable_model, hardware_constraints
            )
            
            # Set training frameworks
            compatibility.training_frameworks = trainable_model.training_frameworks
            
            # Generate recommendations
            compatibility.recommendations = self._generate_recommendations(
                trainable_model, training_type, hardware_constraints
            )
            
            # Estimate training time
            compatibility.estimated_training_time = self._estimate_training_time(
                trainable_model, training_type
            )
            
            # Final compatibility check
            compatibility.is_compatible = len(compatibility.compatibility_issues) == 0
            
            return compatibility
            
        except Exception as e:
            self.logger.error(f"Error checking model compatibility: {e}")
            return ModelCompatibility(
                model_id=model_id,
                is_compatible=False,
                compatibility_issues=[f"Error during compatibility check: {str(e)}"]
            )
    
    def _estimate_memory_requirements(self, model: TrainableModel, training_type: TrainingType) -> float:
        """Estimate system memory requirements for training."""
        base_memory = 2.0  # Base system overhead
        
        if model.parameters:
            param_count = self._extract_parameter_count(model.parameters)
            if param_count:
                # Rough estimation: 4 bytes per parameter for fp32, plus gradients and optimizer states
                model_memory = param_count * 4 / (1024**3)  # Convert to GB
                
                if training_type == TrainingType.FULL_TRAINING:
                    # Full training needs model + gradients + optimizer states
                    return base_memory + model_memory * 4
                elif training_type == TrainingType.FINE_TUNING:
                    # Fine-tuning needs model + gradients + optimizer states for unfrozen layers
                    return base_memory + model_memory * 3
                elif training_type == TrainingType.LORA_ADAPTATION:
                    # LoRA only trains adapter layers
                    return base_memory + model_memory * 1.5
        
        return base_memory + 4.0  # Default estimate
    
    def _estimate_gpu_memory_requirements(self, model: TrainableModel, training_type: TrainingType) -> float:
        """Estimate GPU memory requirements for training."""
        if model.parameters:
            param_count = self._extract_parameter_count(model.parameters)
            if param_count:
                # Model weights in GPU memory
                model_memory = param_count * 2 / (1024**3)  # fp16, convert to GB
                
                if training_type == TrainingType.FULL_TRAINING:
                    # Model + gradients + optimizer states + activations
                    return model_memory * 6
                elif training_type == TrainingType.FINE_TUNING:
                    # Model + gradients + optimizer states + activations (partial)
                    return model_memory * 4
                elif training_type == TrainingType.LORA_ADAPTATION:
                    # Model + LoRA adapters + gradients + activations
                    return model_memory * 2
        
        return 4.0  # Default estimate
    
    def _recommend_batch_size(self, model: TrainableModel, hardware: HardwareConstraints) -> int:
        """Recommend optimal batch size based on model and hardware."""
        if hardware.gpu_count == 0:
            return 1  # CPU training
        
        # Base batch size on available GPU memory
        if hardware.available_gpu_memory_gb >= 24:
            return 16
        elif hardware.available_gpu_memory_gb >= 16:
            return 8
        elif hardware.available_gpu_memory_gb >= 8:
            return 4
        else:
            return 1
    
    def _generate_recommendations(
        self, 
        model: TrainableModel, 
        training_type: TrainingType,
        hardware: HardwareConstraints
    ) -> List[str]:
        """Generate training recommendations."""
        recommendations = []
        
        if hardware.supports_mixed_precision:
            recommendations.append("Use mixed precision (fp16/bf16) to reduce memory usage")
        
        if hardware.available_gpu_memory_gb < 16:
            recommendations.append("Consider using gradient checkpointing to reduce memory usage")
            recommendations.append("Use smaller batch sizes and gradient accumulation")
        
        if training_type == TrainingType.FULL_TRAINING and model.parameters:
            param_count = self._extract_parameter_count(model.parameters)
            if param_count and param_count > 7:
                recommendations.append("Consider using LoRA adaptation instead of full training for large models")
        
        if hardware.gpu_count > 1:
            recommendations.append("Consider using distributed training across multiple GPUs")
        
        return recommendations
    
    def _estimate_training_time(self, model: TrainableModel, training_type: TrainingType) -> str:
        """Estimate training time."""
        if model.parameters:
            param_count = self._extract_parameter_count(model.parameters)
            if param_count:
                if training_type == TrainingType.LORA_ADAPTATION:
                    if param_count <= 1:
                        return "30 minutes - 2 hours"
                    elif param_count <= 7:
                        return "2 - 8 hours"
                    else:
                        return "8 - 24 hours"
                elif training_type == TrainingType.FINE_TUNING:
                    if param_count <= 1:
                        return "1 - 4 hours"
                    elif param_count <= 7:
                        return "4 - 16 hours"
                    else:
                        return "16 hours - 3 days"
                elif training_type == TrainingType.FULL_TRAINING:
                    return "Several days to weeks"
        
        return "Unknown"
    
    def _extract_parameter_count(self, param_str: str) -> Optional[float]:
        """Extract parameter count from string like '7B', '1.3B', etc."""
        if not param_str:
            return None
        
        param_str = param_str.upper().strip()
        try:
            if 'B' in param_str:
                return float(param_str.replace('B', ''))
            elif 'M' in param_str:
                return float(param_str.replace('M', '')) / 1000
            else:
                # Try to parse as number
                return float(param_str) / 1e9  # Assume raw parameter count
        except ValueError:
            return None


class TrainingEnvironmentManager:
    """Manages training environment setup and configuration."""
    
    def __init__(self, base_dir: str = "./training_environments"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
    
    async def setup_environment(
        self, 
        model_id: str, 
        training_type: TrainingType,
        training_mode: TrainingMode,
        job_id: Optional[str] = None
    ) -> TrainingEnvironment:
        """Set up training environment for a model."""
        try:
            job_id = job_id or str(uuid.uuid4())
            
            # Create environment directories
            env_dir = self.base_dir / job_id
            env_dir.mkdir(exist_ok=True)
            
            environment = TrainingEnvironment(
                model_id=model_id,
                training_type=training_type,
                training_mode=training_mode,
                output_dir=env_dir / "output",
                temp_dir=env_dir / "temp",
                model_cache_dir=env_dir / "models",
                data_dir=env_dir / "data",
                checkpoint_dir=env_dir / "checkpoints",
                logs_dir=env_dir / "logs",
                hardware_constraints=HardwareConstraints.detect_current()
            )
            
            # Create all directories
            for dir_path in [
                environment.output_dir,
                environment.temp_dir,
                environment.model_cache_dir,
                environment.data_dir,
                environment.checkpoint_dir,
                environment.logs_dir
            ]:
                dir_path.mkdir(parents=True, exist_ok=True)
            
            # Validate environment
            await self._validate_environment(environment)
            
            self.logger.info(f"Training environment set up for {model_id} at {env_dir}")
            return environment
            
        except Exception as e:
            self.logger.error(f"Failed to set up training environment: {e}")
            raise
    
    async def _validate_environment(self, environment: TrainingEnvironment):
        """Validate training environment setup."""
        try:
            # Check directory permissions
            for dir_path in [environment.output_dir, environment.temp_dir, environment.logs_dir]:
                if not os.access(dir_path, os.W_OK):
                    environment.setup_errors.append(f"No write permission for {dir_path}")
            
            # Check disk space (require at least 10GB)
            disk_usage = shutil.disk_usage(environment.output_dir)
            free_gb = disk_usage.free / (1024**3)
            if free_gb < 10:
                environment.setup_errors.append(f"Insufficient disk space: {free_gb:.1f}GB available, 10GB required")
            
            # Check Python environment
            try:
                import transformers
                import torch
            except ImportError as e:
                environment.setup_errors.append(f"Missing required packages: {e}")
            
            # Check CUDA availability if GPU training
            if environment.hardware_constraints.gpu_count > 0:
                if not torch.cuda.is_available():
                    environment.setup_errors.append("CUDA not available despite GPU detection")
            
            environment.environment_ready = len(environment.setup_errors) == 0
            
        except Exception as e:
            environment.setup_errors.append(f"Environment validation error: {str(e)}")
            environment.environment_ready = False
    
    def cleanup_environment(self, environment: TrainingEnvironment):
        """Clean up training environment."""
        try:
            if environment.temp_dir.exists():
                shutil.rmtree(environment.temp_dir)
            self.logger.info(f"Cleaned up training environment: {environment.output_dir.parent}")
        except Exception as e:
            self.logger.warning(f"Failed to clean up environment: {e}")


class TrainingParameterValidator:
    """Validates training parameters against hardware constraints."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def validate_basic_config(
        self, 
        config: BasicTrainingConfig,
        compatibility: ModelCompatibility,
        hardware: HardwareConstraints
    ) -> Tuple[bool, List[str]]:
        """Validate basic training configuration."""
        issues = []
        
        # Validate batch size
        if config.batch_size > compatibility.recommended_batch_size * 2:
            issues.append(f"Batch size {config.batch_size} may be too large, recommended: {compatibility.recommended_batch_size}")
        
        # Validate learning rate
        if config.learning_rate > 1e-3:
            issues.append(f"Learning rate {config.learning_rate} may be too high for fine-tuning")
        
        # Validate sequence length
        if config.max_length > 2048 and hardware.available_gpu_memory_gb < 16:
            issues.append(f"Max length {config.max_length} may cause memory issues with available GPU memory")
        
        # Validate epochs
        if config.num_epochs > 10:
            issues.append(f"Number of epochs {config.num_epochs} may lead to overfitting")
        
        return len(issues) == 0, issues
    
    def validate_advanced_config(
        self, 
        config: AdvancedTrainingConfig,
        compatibility: ModelCompatibility,
        hardware: HardwareConstraints
    ) -> Tuple[bool, List[str]]:
        """Validate advanced training configuration."""
        issues = []
        
        # Validate precision settings
        if config.bf16 and not hardware.supports_mixed_precision:
            issues.append("BF16 precision not supported on this hardware")
        
        # Validate batch size and gradient accumulation
        effective_batch_size = config.per_device_train_batch_size * config.gradient_accumulation_steps
        if effective_batch_size > compatibility.recommended_batch_size * 4:
            issues.append(f"Effective batch size {effective_batch_size} may be too large")
        
        # Validate LoRA parameters
        if config.training_type == TrainingType.LORA_ADAPTATION:
            if config.lora_r > 64:
                issues.append(f"LoRA rank {config.lora_r} may be too high")
            if config.lora_alpha < config.lora_r:
                issues.append(f"LoRA alpha {config.lora_alpha} should be >= LoRA rank {config.lora_r}")
        
        # Validate optimizer parameters
        if config.weight_decay > 0.1:
            issues.append(f"Weight decay {config.weight_decay} may be too high")
        
        return len(issues) == 0, issues


class FlexibleTrainingInterface:
    """
    Main flexible training interface that provides model compatibility checking,
    training environment setup, and different training modes with hardware validation.
    """
    
    def __init__(
        self,
        enhanced_hf_service: HuggingFaceService,
        training_data_manager: TrainingDataManager,
        system_model_manager: SystemModelManager,
        base_dir: str = "./training_environments"
    ):
        self.enhanced_hf_service = enhanced_hf_service
        self.training_data_manager = training_data_manager
        self.system_model_manager = system_model_manager
        
        # Initialize components
        self.compatibility_checker = ModelCompatibilityChecker(enhanced_hf_service)
        self.environment_manager = TrainingEnvironmentManager(base_dir)
        self.parameter_validator = TrainingParameterValidator()
        
        # Active training jobs
        self.active_jobs: Dict[str, TrainingJob] = {}
        
        self.logger = logging.getLogger(__name__)
    
    async def check_model_compatibility(
        self, 
        model_id: str, 
        training_type: TrainingType
    ) -> ModelCompatibility:
        """Check if a model is compatible for training."""
        hardware = HardwareConstraints.detect_current()
        return await self.compatibility_checker.check_compatibility(
            model_id, training_type, hardware
        )
    
    async def setup_training_environment(
        self, 
        model_id: str, 
        training_type: TrainingType,
        training_mode: TrainingMode = TrainingMode.BASIC
    ) -> TrainingEnvironment:
        """Set up training environment for a model."""
        return await self.environment_manager.setup_environment(
            model_id, training_type, training_mode
        )
    
    async def create_basic_training_job(
        self, 
        config: BasicTrainingConfig
    ) -> TrainingJob:
        """Create a basic training job with preset configurations."""
        try:
            # Check compatibility
            compatibility = await self.check_model_compatibility(
                config.model_id, config.training_type
            )
            
            if not compatibility.is_compatible:
                raise ValueError(f"Model not compatible: {', '.join(compatibility.compatibility_issues)}")
            
            # Validate configuration
            hardware = HardwareConstraints.detect_current()
            is_valid, issues = self.parameter_validator.validate_basic_config(
                config, compatibility, hardware
            )
            
            if not is_valid:
                raise ValueError(f"Configuration issues: {', '.join(issues)}")
            
            # Set up environment
            environment = await self.setup_training_environment(
                config.model_id, config.training_type, TrainingMode.BASIC
            )
            
            if not environment.environment_ready:
                raise RuntimeError(f"Environment setup failed: {', '.join(environment.setup_errors)}")
            
            # Create training job
            job_id = str(uuid.uuid4())
            job = TrainingJob(
                job_id=job_id,
                model_id=config.model_id,
                training_type=config.training_type,
                training_mode=TrainingMode.BASIC,
                status=TrainingStatus.PENDING,
                created_at=datetime.utcnow(),
                total_epochs=config.num_epochs,
                output_dir=str(environment.output_dir)
            )
            
            self.active_jobs[job_id] = job
            
            self.logger.info(f"Created basic training job {job_id} for model {config.model_id}")
            return job
            
        except Exception as e:
            self.logger.error(f"Failed to create basic training job: {e}")
            raise
    
    async def create_advanced_training_job(
        self, 
        config: AdvancedTrainingConfig
    ) -> TrainingJob:
        """Create an advanced training job with full configuration control."""
        try:
            # Check compatibility
            compatibility = await self.check_model_compatibility(
                config.model_id, config.training_type
            )
            
            if not compatibility.is_compatible:
                raise ValueError(f"Model not compatible: {', '.join(compatibility.compatibility_issues)}")
            
            # Validate configuration
            hardware = HardwareConstraints.detect_current()
            is_valid, issues = self.parameter_validator.validate_advanced_config(
                config, compatibility, hardware
            )
            
            if not is_valid:
                raise ValueError(f"Configuration issues: {', '.join(issues)}")
            
            # Set up environment
            environment = await self.setup_training_environment(
                config.model_id, config.training_type, TrainingMode.ADVANCED
            )
            
            if not environment.environment_ready:
                raise RuntimeError(f"Environment setup failed: {', '.join(environment.setup_errors)}")
            
            # Create training job
            job_id = str(uuid.uuid4())
            job = TrainingJob(
                job_id=job_id,
                model_id=config.model_id,
                training_type=config.training_type,
                training_mode=TrainingMode.ADVANCED,
                status=TrainingStatus.PENDING,
                created_at=datetime.utcnow(),
                total_epochs=config.num_epochs,
                output_dir=str(environment.output_dir)
            )
            
            self.active_jobs[job_id] = job
            
            self.logger.info(f"Created advanced training job {job_id} for model {config.model_id}")
            return job
            
        except Exception as e:
            self.logger.error(f"Failed to create advanced training job: {e}")
            raise
    
    async def start_training_job(self, job_id: str) -> bool:
        """Start a training job."""
        try:
            job = self.active_jobs.get(job_id)
            if not job:
                raise ValueError(f"Training job {job_id} not found")
            
            if job.status != TrainingStatus.PENDING:
                raise ValueError(f"Job {job_id} is not in pending status")
            
            # Update job status
            job.status = TrainingStatus.PREPARING
            job.started_at = datetime.utcnow()
            
            # Start training in background
            asyncio.create_task(self._run_training_job(job))
            
            self.logger.info(f"Started training job {job_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start training job {job_id}: {e}")
            if job_id in self.active_jobs:
                self.active_jobs[job_id].status = TrainingStatus.FAILED
                self.active_jobs[job_id].error_message = str(e)
            return False
    
    async def _run_training_job(self, job: TrainingJob):
        """Run training job (placeholder implementation)."""
        try:
            # This is a placeholder implementation
            # In a real implementation, this would:
            # 1. Load the model and tokenizer
            # 2. Prepare the training data
            # 3. Set up the training loop
            # 4. Run training with progress updates
            # 5. Save the trained model
            
            job.status = TrainingStatus.TRAINING
            
            # Simulate training progress
            for epoch in range(job.total_epochs):
                job.current_epoch = epoch + 1
                job.progress = (epoch + 1) / job.total_epochs
                
                # Simulate training time
                await asyncio.sleep(1)
                
                job.logs.append(f"Completed epoch {epoch + 1}/{job.total_epochs}")
            
            job.status = TrainingStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.progress = 1.0
            
            self.logger.info(f"Training job {job.job_id} completed successfully")
            
        except Exception as e:
            job.status = TrainingStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            self.logger.error(f"Training job {job.job_id} failed: {e}")
    
    def get_training_job(self, job_id: str) -> Optional[TrainingJob]:
        """Get training job by ID."""
        return self.active_jobs.get(job_id)
    
    def list_training_jobs(self) -> List[TrainingJob]:
        """List all training jobs."""
        return list(self.active_jobs.values())
    
    async def cancel_training_job(self, job_id: str) -> bool:
        """Cancel a training job."""
        try:
            job = self.active_jobs.get(job_id)
            if not job:
                return False
            
            if job.status in [TrainingStatus.COMPLETED, TrainingStatus.FAILED, TrainingStatus.CANCELLED]:
                return False
            
            job.status = TrainingStatus.CANCELLED
            job.completed_at = datetime.utcnow()
            
            self.logger.info(f"Cancelled training job {job_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to cancel training job {job_id}: {e}")
            return False
    
    def get_hardware_constraints(self) -> HardwareConstraints:
        """Get current hardware constraints."""
        return HardwareConstraints.detect_current()
    
    async def get_trainable_models(
        self, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[TrainableModel]:
        """Get list of trainable models with optional filtering."""
        try:
            # Use enhanced HuggingFace service to get trainable models
            # This would integrate with the existing model discovery
            models = await self.enhanced_hf_service.search_models(
                query="", 
                filters=filters or {}
            )
            
            # Filter for trainable models
            trainable_models = []
            for model in models:
                if hasattr(model, 'supports_fine_tuning') and model.supports_fine_tuning:
                    trainable_models.append(model)
            
            return trainable_models
            
        except Exception as e:
            self.logger.error(f"Failed to get trainable models: {e}")
            return []

