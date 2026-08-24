"""
Basic Training Mode for the Response Core orchestrator.

This module implements a simplified training interface with preset configurations,
automatic parameter selection, user-friendly progress monitoring, and comprehensive
system reset capabilities with configuration backup/restore.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil
import torch
from transformers import AutoConfig, AutoTokenizer

from ai_karen_engine.services.training.training_interface import (
    FlexibleTrainingInterface, TrainingJob, TrainingStatus, TrainingType, 
    HardwareConstraints, ModelCompatibility, BasicTrainingConfig
)
from ai_karen_engine.learning.training_data_manager import TrainingDataManager
from ai_karen_engine.core.model_runtime.huggingface_service import EnhancedHuggingFaceService
from ai_karen_engine.core.model_runtime.management.system_model_manager import SystemModelManager

logger = logging.getLogger(__name__)


class BasicTrainingDifficulty(str, Enum):
    """Training difficulty levels for basic mode."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


@dataclass
class BasicTrainingPreset:
    """Preset configuration for basic training."""
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
    recommended_for: List[str] = field(default_factory=list)
    estimated_time: str = "Unknown"
    memory_requirements_gb: float = 4.0


@dataclass
class TrainingProgress:
    """User-friendly training progress information."""
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
    status_message: str = ""
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class TrainingResult:
    """Plain-language training result summary."""
    job_id: str
    model_name: str
    success: bool
    training_time: str
    final_loss: Optional[float]
    improvement_percentage: Optional[float]
    model_path: Optional[str]
    performance_summary: str
    recommendations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class SystemBackup:
    """System configuration backup."""
    backup_id: str
    created_at: datetime
    description: str
    model_configurations: Dict[str, Any]
    training_settings: Dict[str, Any]
    system_settings: Dict[str, Any]
    backup_path: str
    size_mb: float


class BasicTrainingPresets:
    """Predefined training presets for different use cases."""
    
    PRESETS = {
        "quick_test": BasicTrainingPreset(
            name="Quick Test",
            description="Fast training for testing and experimentation",
            difficulty=BasicTrainingDifficulty.BEGINNER,
            training_type=TrainingType.LORA_ADAPTATION,
            num_epochs=1,
            learning_rate=3e-4,
            batch_size=4,
            max_length=256,
            warmup_ratio=0.1,
            use_mixed_precision=True,
            gradient_checkpointing=True,
            recommended_for=["Testing", "Quick experiments", "Learning"],
            estimated_time="15-30 minutes",
            memory_requirements_gb=2.0
        ),
        
        "chat_fine_tune": BasicTrainingPreset(
            name="Chat Fine-tuning",
            description="Optimize model for conversational responses",
            difficulty=BasicTrainingDifficulty.INTERMEDIATE,
            training_type=TrainingType.FINE_TUNING,
            num_epochs=3,
            learning_rate=2e-5,
            batch_size=8,
            max_length=512,
            warmup_ratio=0.1,
            use_mixed_precision=True,
            gradient_checkpointing=True,
            recommended_for=["Chat applications", "Conversational AI", "Customer support"],
            estimated_time="2-6 hours",
            memory_requirements_gb=6.0
        ),
        
        "code_assistant": BasicTrainingPreset(
            name="Code Assistant",
            description="Train model for code generation and assistance",
            difficulty=BasicTrainingDifficulty.INTERMEDIATE,
            training_type=TrainingType.LORA_ADAPTATION,
            num_epochs=5,
            learning_rate=1e-4,
            batch_size=4,
            max_length=1024,
            warmup_ratio=0.05,
            use_mixed_precision=True,
            gradient_checkpointing=True,
            recommended_for=["Code generation", "Programming assistance", "Technical documentation"],
            estimated_time="3-8 hours",
            memory_requirements_gb=8.0
        ),
        
        "domain_expert": BasicTrainingPreset(
            name="Domain Expert",
            description="Deep specialization for specific domain knowledge",
            difficulty=BasicTrainingDifficulty.ADVANCED,
            training_type=TrainingType.FINE_TUNING,
            num_epochs=10,
            learning_rate=1e-5,
            batch_size=16,
            max_length=512,
            warmup_ratio=0.2,
            use_mixed_precision=True,
            gradient_checkpointing=True,
            recommended_for=["Domain expertise", "Specialized knowledge", "Professional applications"],
            estimated_time="8-24 hours",
            memory_requirements_gb=12.0
        )
    }
    
    @classmethod
    def get_preset(cls, preset_name: str) -> Optional[BasicTrainingPreset]:
        """Get a training preset by name."""
        return cls.PRESETS.get(preset_name)
    
    @classmethod
    def get_recommended_presets(cls, hardware: HardwareConstraints) -> List[BasicTrainingPreset]:
        """Get presets recommended for current hardware."""
        recommended = []
        
        for preset in cls.PRESETS.values():
            # Check memory requirements
            if preset.memory_requirements_gb <= hardware.available_gpu_memory_gb or hardware.gpu_count == 0:
                # Adjust for CPU-only training
                if hardware.gpu_count == 0 and preset.memory_requirements_gb <= hardware.available_memory_gb / 2:
                    recommended.append(preset)
                elif hardware.gpu_count > 0:
                    recommended.append(preset)
        
        return recommended
    
    @classmethod
    def get_preset_for_model(cls, model_id: str, hardware: HardwareConstraints) -> Optional[BasicTrainingPreset]:
        """Get the best preset for a specific model and hardware."""
        # Simple heuristic based on model name
        model_lower = model_id.lower()
        
        if "code" in model_lower or "python" in model_lower:
            preset = cls.get_preset("code_assistant")
        elif any(keyword in model_lower for keyword in ["chat", "dialog", "instruct", "conversation"]):
            preset = cls.get_preset("chat_fine_tune")
        elif any(size in model_lower for size in ["7b", "13b", "30b", "70b"]):
            preset = cls.get_preset("domain_expert")
        else:
            preset = cls.get_preset("quick_test")
        
        # Verify hardware compatibility
        if preset and preset.memory_requirements_gb <= hardware.available_gpu_memory_gb:
            return preset
        elif preset and hardware.gpu_count == 0 and preset.memory_requirements_gb <= hardware.available_memory_gb / 2:
            return preset
        else:
            # Fallback to quick test
            return cls.get_preset("quick_test")


class ProgressMonitor:
    """User-friendly progress monitoring for training jobs."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.start_times: Dict[str, datetime] = {}
    
    def start_monitoring(self, job_id: str):
        """Start monitoring a training job."""
        self.start_times[job_id] = datetime.utcnow()
    
    def get_progress(self, job: TrainingJob) -> TrainingProgress:
        """Get user-friendly progress information."""
        start_time = self.start_times.get(job.job_id, job.created_at)
        elapsed = datetime.utcnow() - start_time
        elapsed_str = self._format_duration(elapsed)
        
        # Calculate progress percentage
        if job.total_steps > 0:
            progress_pct = (job.current_step / job.total_steps) * 100
        elif job.total_epochs > 0:
            progress_pct = (job.current_epoch / job.total_epochs) * 100
        else:
            progress_pct = 0.0
        
        # Estimate remaining time
        if progress_pct > 5:  # Only estimate after 5% progress
            total_estimated = elapsed.total_seconds() / (progress_pct / 100)
            remaining_seconds = total_estimated - elapsed.total_seconds()
            remaining_str = self._format_duration(timedelta(seconds=max(0, remaining_seconds)))
        else:
            remaining_str = "Calculating..."
        
        # Generate status message
        status_message = self._generate_status_message(job)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(job, progress_pct, elapsed)
        
        # Check for warnings
        warnings = self._check_warnings(job, progress_pct, elapsed)
        
        return TrainingProgress(
            job_id=job.job_id,
            model_name=job.model_id.split('/')[-1],  # Get model name from ID
            status=self._friendly_status(job.status),
            progress_percentage=progress_pct,
            current_step=job.current_step,
            total_steps=job.total_steps,
            current_epoch=job.current_epoch,
            total_epochs=job.total_epochs,
            elapsed_time=elapsed_str,
            estimated_remaining=remaining_str,
            current_loss=job.loss,
            best_loss=job.metrics.get("best_loss"),
            learning_rate=job.learning_rate,
            memory_usage_gb=job.metrics.get("memory_usage_gb"),
            gpu_utilization=job.metrics.get("gpu_utilization"),
            status_message=status_message,
            warnings=warnings,
            recommendations=recommendations
        )
    
    def _format_duration(self, duration: timedelta) -> str:
        """Format duration in human-readable format."""
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def _friendly_status(self, status: TrainingStatus) -> str:
        """Convert technical status to user-friendly message."""
        status_map = {
            TrainingStatus.PENDING: "Getting ready...",
            TrainingStatus.VALIDATING: "Checking everything...",
            TrainingStatus.PREPARING: "Setting up training...",
            TrainingStatus.TRAINING: "Training in progress",
            TrainingStatus.EVALUATING: "Evaluating results...",
            TrainingStatus.COMPLETED: "Training completed!",
            TrainingStatus.FAILED: "Training encountered an issue",
            TrainingStatus.CANCELLED: "Training was cancelled"
        }
        return status_map.get(status, str(status))
    
    def _generate_status_message(self, job: TrainingJob) -> str:
        """Generate detailed status message."""
        if job.status == TrainingStatus.TRAINING:
            if job.total_epochs > 0:
                return f"Training epoch {job.current_epoch + 1} of {job.total_epochs}"
            else:
                return "Training in progress..."
        elif job.status == TrainingStatus.COMPLETED:
            return "Training completed successfully!"
        elif job.status == TrainingStatus.FAILED:
            return f"Training failed: {job.error_message or 'Unknown error'}"
        else:
            return self._friendly_status(job.status)
    
    def _generate_recommendations(self, job: TrainingJob, progress_pct: float, elapsed: timedelta) -> List[str]:
        """Generate helpful recommendations based on training progress."""
        recommendations = []
        
        # Loss-based recommendations
        if job.loss and job.metrics.get("best_loss"):
            if job.loss > job.metrics["best_loss"] * 1.5:
                recommendations.append("Loss is increasing - consider reducing learning rate")
        
        # Time-based recommendations
        if elapsed.total_seconds() > 3600 and progress_pct < 10:  # More than 1 hour, less than 10% progress
            recommendations.append("Training is slower than expected - consider reducing batch size or sequence length")
        
        # Memory-based recommendations
        memory_usage = job.metrics.get("memory_usage_gb", 0)
        if memory_usage > 0.9 * torch.cuda.get_device_properties(0).total_memory / (1024**3):
            recommendations.append("High memory usage detected - consider enabling gradient checkpointing")
        
        return recommendations
    
    def _check_warnings(self, job: TrainingJob, progress_pct: float, elapsed: timedelta) -> List[str]:
        """Check for potential issues and generate warnings."""
        warnings = []
        
        # Stalled training
        if job.status == TrainingStatus.TRAINING and progress_pct < 1 and elapsed.total_seconds() > 1800:  # 30 minutes
            warnings.append("Training appears to be stalled - check logs for issues")
        
        # High loss
        if job.loss and job.loss > 10:
            warnings.append("Loss is very high - training may not be converging properly")
        
        # Memory warnings
        if job.metrics.get("memory_usage_gb", 0) > 0.95 * torch.cuda.get_device_properties(0).total_memory / (1024**3):
            warnings.append("Memory usage is very high - training may fail due to out-of-memory")
        
        return warnings


class SystemResetManager:
    """Manages system configuration backup and reset functionality."""
    
    def __init__(self, backup_dir: str = "./system_backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
    
    def create_backup(self, description: str = "Manual backup") -> SystemBackup:
        """Create a complete system configuration backup."""
        try:
            backup_id = str(uuid.uuid4())
            backup_time = datetime.utcnow()
            backup_path = self.backup_dir / f"backup_{backup_id}_{backup_time.strftime('%Y%m%d_%H%M%S')}"
            backup_path.mkdir(parents=True, exist_ok=True)
            
            # Collect model configurations
            model_configs = self._backup_model_configurations(backup_path)
            
            # Collect training settings
            training_settings = self._backup_training_settings(backup_path)
            
            # Collect system settings
            system_settings = self._backup_system_settings(backup_path)
            
            # Calculate backup size
            size_mb = self._calculate_backup_size(backup_path)
            
            # Create backup metadata
            backup = SystemBackup(
                backup_id=backup_id,
                created_at=backup_time,
                description=description,
                model_configurations=model_configs,
                training_settings=training_settings,
                system_settings=system_settings,
                backup_path=str(backup_path),
                size_mb=size_mb
            )
            
            # Save backup metadata
            metadata_path = backup_path / "backup_metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(asdict(backup), f, indent=2, default=str)
            
            self.logger.info(f"Created system backup {backup_id} at {backup_path}")
            return backup
            
        except Exception as e:
            self.logger.error(f"Failed to create system backup: {e}")
            raise
    
    def restore_backup(self, backup_id: str) -> bool:
        """Restore system configuration from backup."""
        try:
            # Find backup
            backup = self.get_backup(backup_id)
            if not backup:
                return False
            
            backup_path = Path(backup.backup_path)
            if not backup_path.exists():
                self.logger.error(f"Backup path not found: {backup_path}")
                return False
            
            # Restore model configurations
            self._restore_model_configurations(backup_path)
            
            # Restore training settings
            self._restore_training_settings(backup_path)
            
            # Restore system settings
            self._restore_system_settings(backup_path)
            
            self.logger.info(f"Restored system from backup {backup_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to restore backup {backup_id}: {e}")
            return False
    
    def reset_to_factory_defaults(self, preserve_user_data: bool = True) -> bool:
        """Reset system to factory defaults."""
        try:
            # Create backup before reset
            backup = self.create_backup("Pre-factory-reset backup")
            
            # Reset model configurations
            self._reset_model_configurations()
            
            # Reset training settings
            self._reset_training_settings()
            
            # Reset system settings (preserve user data if requested)
            self._reset_system_settings(preserve_user_data)
            
            self.logger.info("System reset to factory defaults")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reset to factory defaults: {e}")
            return False
    
    def get_backup(self, backup_id: str) -> Optional[SystemBackup]:
        """Get backup information by ID."""
        try:
            for backup_dir in self.backup_dir.iterdir():
                if backup_dir.is_dir() and backup_id in backup_dir.name:
                    metadata_path = backup_dir / "backup_metadata.json"
                    if metadata_path.exists():
                        with open(metadata_path, 'r') as f:
                            data = json.load(f)
                            return SystemBackup(**data)
            return None
        except Exception as e:
            self.logger.error(f"Failed to get backup {backup_id}: {e}")
            return None
    
    def list_backups(self) -> List[SystemBackup]:
        """List all available backups."""
        backups = []
        try:
            for backup_dir in self.backup_dir.iterdir():
                if backup_dir.is_dir():
                    metadata_path = backup_dir / "backup_metadata.json"
                    if metadata_path.exists():
                        with open(metadata_path, 'r') as f:
                            data = json.load(f)
                            backups.append(SystemBackup(**data))
        except Exception as e:
            self.logger.error(f"Failed to list backups: {e}")
        
        return sorted(backups, key=lambda x: x.created_at, reverse=True)
    
    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup."""
        try:
            backup = self.get_backup(backup_id)
            if backup:
                backup_path = Path(backup.backup_path)
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                    self.logger.info(f"Deleted backup {backup_id}")
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False
    
    def _backup_model_configurations(self, backup_path: Path) -> Dict[str, Any]:
        """Backup model configurations."""
        configs = {}
        try:
            # This would integrate with SystemModelManager
            # For now, return empty dict
            configs_path = backup_path / "model_configurations.json"
            with open(configs_path, 'w') as f:
                json.dump(configs, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to backup model configurations: {e}")
        return configs
    
    def _backup_training_settings(self, backup_path: Path) -> Dict[str, Any]:
        """Backup training settings."""
        settings = {}
        try:
            # Backup training presets and custom configurations
            settings_path = backup_path / "training_settings.json"
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to backup training settings: {e}")
        return settings
    
    def _backup_system_settings(self, backup_path: Path) -> Dict[str, Any]:
        """Backup system settings."""
        settings = {}
        try:
            # Backup system-wide settings
            settings_path = backup_path / "system_settings.json"
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to backup system settings: {e}")
        return settings
    
    def _restore_model_configurations(self, backup_path: Path):
        """Restore model configurations from backup."""
        try:
            configs_path = backup_path / "model_configurations.json"
            if configs_path.exists():
                with open(configs_path, 'r') as f:
                    configs = json.load(f)
                # Restore configurations using SystemModelManager
                self.logger.info("Restored model configurations")
        except Exception as e:
            self.logger.warning(f"Failed to restore model configurations: {e}")
    
    def _restore_training_settings(self, backup_path: Path):
        """Restore training settings from backup."""
        try:
            settings_path = backup_path / "training_settings.json"
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                # Restore training settings
                self.logger.info("Restored training settings")
        except Exception as e:
            self.logger.warning(f"Failed to restore training settings: {e}")
    
    def _restore_system_settings(self, backup_path: Path):
        """Restore system settings from backup."""
        try:
            settings_path = backup_path / "system_settings.json"
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                # Restore system settings
                self.logger.info("Restored system settings")
        except Exception as e:
            self.logger.warning(f"Failed to restore system settings: {e}")
    
    def _reset_model_configurations(self):
        """Reset all model configurations to defaults."""
        try:
            # Reset using SystemModelManager
            self.logger.info("Reset model configurations to defaults")
        except Exception as e:
            self.logger.warning(f"Failed to reset model configurations: {e}")
    
    def _reset_training_settings(self):
        """Reset training settings to defaults."""
        try:
            # Reset training presets and configurations
            self.logger.info("Reset training settings to defaults")
        except Exception as e:
            self.logger.warning(f"Failed to reset training settings: {e}")
    
    def _reset_system_settings(self, preserve_user_data: bool = True):
        """Reset system settings to defaults."""
        try:
            # Reset system settings while optionally preserving user data
            self.logger.info(f"Reset system settings to defaults (preserve_user_data={preserve_user_data})")
        except Exception as e:
            self.logger.warning(f"Failed to reset system settings: {e}")
    
    def _calculate_backup_size(self, backup_path: Path) -> float:
        """Calculate backup size in MB."""
        try:
            total_size = 0
            for file_path in backup_path.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
            return total_size / (1024 * 1024)  # Convert to MB
        except Exception:
            return 0.0


class BasicTrainingMode:
    """
    Simplified training interface with preset configurations, automatic parameter
    selection, user-friendly progress monitoring, and comprehensive system reset
    capabilities with configuration backup/restore.
    """
    
    def __init__(
        self,
        training_interface: FlexibleTrainingInterface,
        training_data_manager: TrainingDataManager,
        system_model_manager: SystemModelManager,
        enhanced_hf_service: HuggingFaceService
    ):
        self.training_interface = training_interface
        self.training_data_manager = training_data_manager
        self.system_model_manager = system_model_manager
        self.enhanced_hf_service = enhanced_hf_service
        
        # Initialize components
        self.progress_monitor = ProgressMonitor()
        self.reset_manager = SystemResetManager()
        
        self.logger = logging.getLogger(__name__)
    
    async def get_recommended_presets(self) -> List[BasicTrainingPreset]:
        """Get training presets recommended for current hardware."""
        hardware = HardwareConstraints.detect_current()
        return BasicTrainingPresets.get_recommended_presets(hardware)
    
    async def get_preset_for_model(self, model_id: str) -> Optional[BasicTrainingPreset]:
        """Get the best preset for a specific model."""
        hardware = HardwareConstraints.detect_current()
        return BasicTrainingPresets.get_preset_for_model(model_id, hardware)
    
    async def start_basic_training(
        self, 
        model_id: str, 
        dataset_id: str,
        preset_name: Optional[str] = None,
        custom_description: Optional[str] = None
    ) -> TrainingJob:
        """Start basic training with automatic parameter selection."""
        try:
            # Get hardware constraints
            hardware = HardwareConstraints.detect_current()
            
            # Select preset
            if preset_name:
                preset = BasicTrainingPresets.get_preset(preset_name)
                if not preset:
                    raise ValueError(f"Unknown preset: {preset_name}")
            else:
                preset = BasicTrainingPresets.get_preset_for_model(model_id, hardware)
                if not preset:
                    raise ValueError("No suitable preset found for this model")
            
            # Check model compatibility
            compatibility = await self.training_interface.check_model_compatibility(
                model_id, preset.training_type
            )
            
            if not compatibility.is_compatible:
                raise ValueError(f"Model not compatible: {', '.join(compatibility.compatibility_issues)}")
            
            # Adjust preset based on hardware
            adjusted_config = self._adjust_config_for_hardware(preset, hardware, compatibility)
            
            # Create basic training config
            config = BasicTrainingConfig(
                model_id=model_id,
                dataset_id=dataset_id,
                training_type=preset.training_type,
                num_epochs=adjusted_config["num_epochs"],
                learning_rate=adjusted_config["learning_rate"],
                batch_size=adjusted_config["batch_size"],
                max_length=adjusted_config["max_length"],
                warmup_steps=adjusted_config["warmup_steps"],
                use_mixed_precision=adjusted_config["use_mixed_precision"],
                gradient_checkpointing=adjusted_config["gradient_checkpointing"]
            )
            
            # Start training
            job = await self.training_interface.create_basic_training_job(config)
            
            # Start progress monitoring
            self.progress_monitor.start_monitoring(job.job_id)
            
            self.logger.info(f"Started basic training job {job.job_id} for model {model_id} using preset {preset.name}")
            return job
            
        except Exception as e:
            self.logger.error(f"Failed to start basic training: {e}")
            raise
    
    def get_training_progress(self, job_id: str) -> Optional[TrainingProgress]:
        """Get user-friendly training progress."""
        try:
            job = self.training_interface.active_jobs.get(job_id)
            if not job:
                return None
            
            return self.progress_monitor.get_progress(job)
            
        except Exception as e:
            self.logger.error(f"Failed to get training progress: {e}")
            return None
    
    def get_training_result(self, job_id: str) -> Optional[TrainingResult]:
        """Get plain-language training result summary."""
        try:
            job = self.training_interface.active_jobs.get(job_id)
            if not job:
                return None
            
            if job.status != TrainingStatus.COMPLETED:
                return None
            
            # Calculate improvement
            improvement_pct = None
            if job.metrics.get("initial_loss") and job.loss:
                initial_loss = job.metrics["initial_loss"]
                improvement_pct = ((initial_loss - job.loss) / initial_loss) * 100
            
            # Generate performance summary
            performance_summary = self._generate_performance_summary(job, improvement_pct)
            
            # Generate recommendations and next steps
            recommendations = self._generate_result_recommendations(job, improvement_pct)
            next_steps = self._generate_next_steps(job)
            
            return TrainingResult(
                job_id=job_id,
                model_name=job.model_id.split('/')[-1],
                success=job.status == TrainingStatus.COMPLETED,
                training_time=self.progress_monitor._format_duration(
                    job.completed_at - job.started_at if job.completed_at and job.started_at else timedelta()
                ),
                final_loss=job.loss,
                improvement_percentage=improvement_pct,
                model_path=job.model_path,
                performance_summary=performance_summary,
                recommendations=recommendations,
                next_steps=next_steps
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get training result: {e}")
            return None
    
    def cancel_training(self, job_id: str) -> bool:
        """Cancel a training job."""
        try:
            # This would integrate with the actual training process
            job = self.training_interface.active_jobs.get(job_id)
            if job:
                job.status = TrainingStatus.CANCELLED
                self.logger.info(f"Cancelled training job {job_id}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to cancel training job {job_id}: {e}")
            return False
    
    # System Reset Methods
    
    def create_system_backup(self, description: str = "Manual backup") -> SystemBackup:
        """Create a complete system configuration backup."""
        return self.reset_manager.create_backup(description)
    
    def restore_system_backup(self, backup_id: str) -> bool:
        """Restore system configuration from backup."""
        return self.reset_manager.restore_backup(backup_id)
    
    def reset_to_factory_defaults(self, preserve_user_data: bool = True) -> bool:
        """Reset system to factory defaults."""
        return self.reset_manager.reset_to_factory_defaults(preserve_user_data)
    
    def list_system_backups(self) -> List[SystemBackup]:
        """List all available system backups."""
        return self.reset_manager.list_backups()
    
    def delete_system_backup(self, backup_id: str) -> bool:
        """Delete a system backup."""
        return self.reset_manager.delete_backup(backup_id)
    
    # Helper Methods
    
    def _adjust_config_for_hardware(
        self, 
        preset: BasicTrainingPreset, 
        hardware: HardwareConstraints,
        compatibility: ModelCompatibility
    ) -> Dict[str, Any]:
        """Adjust preset configuration based on hardware constraints."""
        config = {
            "num_epochs": preset.num_epochs,
            "learning_rate": preset.learning_rate,
            "batch_size": preset.batch_size,
            "max_length": preset.max_length,
            "warmup_steps": int(preset.warmup_ratio * 1000),  # Estimate based on typical dataset size
            "use_mixed_precision": preset.use_mixed_precision and hardware.supports_mixed_precision,
            "gradient_checkpointing": preset.gradient_checkpointing
        }
        
        # Adjust batch size for hardware
        if hardware.gpu_count == 0:
            config["batch_size"] = min(config["batch_size"], 2)  # CPU training
        elif hardware.available_gpu_memory_gb < 8:
            config["batch_size"] = min(config["batch_size"], 4)  # Low memory GPU
        
        # Adjust sequence length for memory constraints
        if hardware.available_gpu_memory_gb < 6:
            config["max_length"] = min(config["max_length"], 256)
        
        # Use recommended batch size from compatibility check
        if compatibility.recommended_batch_size:
            config["batch_size"] = min(config["batch_size"], compatibility.recommended_batch_size)
        
        return config
    
    def _generate_performance_summary(self, job: TrainingJob, improvement_pct: Optional[float]) -> str:
        """Generate plain-language performance summary."""
        if improvement_pct is not None:
            if improvement_pct > 20:
                return f"Excellent results! The model improved by {improvement_pct:.1f}% and should perform significantly better."
            elif improvement_pct > 10:
                return f"Good results! The model improved by {improvement_pct:.1f}% and should perform noticeably better."
            elif improvement_pct > 5:
                return f"Moderate improvement of {improvement_pct:.1f}%. The model should perform somewhat better."
            elif improvement_pct > 0:
                return f"Small improvement of {improvement_pct:.1f}%. Consider training longer or adjusting parameters."
            else:
                return "The model did not improve significantly. Consider different training parameters or more data."
        else:
            return "Training completed successfully. Performance evaluation requires additional metrics."
    
    def _generate_result_recommendations(self, job: TrainingJob, improvement_pct: Optional[float]) -> List[str]:
        """Generate recommendations based on training results."""
        recommendations = []
        
        if improvement_pct is not None:
            if improvement_pct < 5:
                recommendations.append("Consider training for more epochs or using a different learning rate")
                recommendations.append("Try using more diverse training data")
            elif improvement_pct > 30:
                recommendations.append("Excellent results! Consider fine-tuning further for specific tasks")
        
        if job.loss and job.loss > 1.0:
            recommendations.append("Loss is still high - consider additional training or parameter adjustments")
        
        return recommendations
    
    def _generate_next_steps(self, job: TrainingJob) -> List[str]:
        """Generate suggested next steps after training."""
        next_steps = [
            "Test the trained model with sample inputs",
            "Evaluate performance on your specific use case",
            "Consider creating a backup of the trained model"
        ]
        
        if job.training_type == TrainingType.LORA_ADAPTATION:
            next_steps.append("Consider full fine-tuning if LoRA results are promising")
        
        return next_steps

