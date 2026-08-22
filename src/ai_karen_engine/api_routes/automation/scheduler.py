"""
API routes for the autonomous training scheduler.

This module provides REST API endpoints for managing cron-based autonomous training
schedules, including creation, configuration, monitoring, and notification management.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

try:
    from pydantic import BaseModel, Field, validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field, validator

from ai_karen_engine.services.scheduling.scheduler_manager import (
    SchedulerManager,
    AutonomousConfig,
    NotificationConfig,
    SafetyControls,
    ScheduleStatus,
    NotificationType,
    SafetyLevel,
)
from ai_karen_engine.learning.autonomous_learner import AutonomousLearner
from ai_karen_engine.core.cortex.analysis import SpacyAnalyzer
from ai_karen_engine.core.memory.memory_service import WebUIMemoryService

# Simple auth imports
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.services.audit.training_audit_logger import get_training_audit_logger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# Initialize audit logger
training_audit_logger = get_training_audit_logger()
_global_scheduler_manager: Optional[SchedulerManager] = None


def get_scheduler_manager() -> SchedulerManager:
    """Get the global scheduler manager instance."""
    global _global_scheduler_manager

    if _global_scheduler_manager is None:
        try:
            memory_service = WebUIMemoryService()
            learner = AutonomousLearner(
                spacy_analyzer=SpacyAnalyzer(),
                memory_service=memory_service,
            )
            _global_scheduler_manager = SchedulerManager(
                autonomous_learner=learner,
                memory_service=memory_service,
            )
        except Exception as e:
            logger.error(f"Failed to get scheduler manager: {e}")
            raise HTTPException(
                status_code=503, detail="Scheduler manager not available"
            )

    return _global_scheduler_manager


async def require_admin_user(
    current_user: dict = Depends(bypass_user_context_func),
) -> dict:
    """Require admin user for scheduler operations (simplified)."""
    user_roles = current_user.get("roles", [])
    if "admin" not in user_roles:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


# Pydantic models for API


class NotificationConfigModel(BaseModel):
    """Notification configuration model."""

    enabled: bool = True
    types: List[NotificationType] = [NotificationType.LOG]

    # Email configuration
    email_smtp_host: Optional[str] = None
    email_smtp_port: int = 587
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_recipients: List[str] = []
    email_use_tls: bool = True

    # Webhook configuration
    webhook_url: Optional[str] = None
    webhook_headers: Dict[str, str] = {}
    webhook_timeout: int = 30

    # Memory storage configuration
    memory_tenant_id: Optional[str] = None
    memory_importance_score: int = 8


class SafetyControlsModel(BaseModel):
    """Safety controls model."""

    level: SafetyLevel = SafetyLevel.MODERATE

    # Data quality controls
    min_data_threshold: int = Field(100, ge=1, le=100000)
    max_data_threshold: int = Field(10000, ge=100, le=1000000)
    quality_threshold: float = Field(0.7, ge=0.0, le=1.0)

    # Training controls
    max_training_time_minutes: int = Field(60, ge=1, le=1440)
    validation_threshold: float = Field(0.85, ge=0.0, le=1.0)
    rollback_on_degradation: bool = True

    # Resource controls
    max_memory_usage_mb: int = Field(2048, ge=512, le=32768)
    max_cpu_usage_percent: float = Field(80.0, ge=10.0, le=100.0)

    # Failure controls
    max_consecutive_failures: int = Field(3, ge=1, le=10)
    failure_cooldown_hours: int = Field(24, ge=1, le=168)

    # Backup controls
    backup_before_training: bool = True
    max_backup_retention_days: int = Field(30, ge=1, le=365)


class AutonomousConfigModel(BaseModel):
    """Autonomous configuration model."""

    enabled: bool = False
    training_schedule: str = "0 2 * * *"
    timezone: str = "UTC"


# RBAC-protected endpoints


@router.get("/schedules")
async def list_schedules(
    current_user: dict = Depends(bypass_user_context_func),
) -> Dict[str, Any]:
    """List all training schedules (requires user role)."""
    # Simple role check - user or admin role required
    user_roles = current_user.get("roles", [])
    if not any(role in user_roles for role in ["admin", "user"]):
        raise HTTPException(status_code=403, detail="User privileges required")

    try:
        manager = get_scheduler_manager()
        schedules = await manager.list_schedules(user_id=current_user.get("user_id"))

        return {
            "schedules": [schedule.to_dict() for schedule in schedules],
            "total": len(schedules),
        }

    except Exception as e:
        logger.error(f"Failed to list schedules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedules")
async def create_schedule(
    config: AutonomousConfigModel, current_user: dict = Depends(require_admin_user)
) -> Dict[str, Any]:
    """Create a new training schedule (requires admin privileges)."""
    try:
        manager = get_scheduler_manager()

        # Convert to internal config format
        autonomous_config = AutonomousConfig(
            enabled=config.enabled,
            training_schedule=config.training_schedule,
            timezone=config.timezone,
        )

        schedule_id = await manager.create_schedule(
            config=autonomous_config, created_by=current_user.get("user_id")
        )

        # Audit log
        training_audit_logger.log_config_updated(
            user=current_user,
            config_type="training_schedule",
            config_changes={
                "schedule_id": schedule_id,
                "enabled": config.enabled,
                "training_schedule": config.training_schedule,
                "timezone": config.timezone,
            },
        )

        return {
            "schedule_id": schedule_id,
            "message": "Training schedule created successfully",
        }

    except Exception as e:
        logger.error(f"Failed to create schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    config: AutonomousConfigModel,
    current_user: dict = Depends(require_admin_user),
) -> Dict[str, str]:
    """Update a training schedule (requires admin privileges)."""
    try:
        manager = get_scheduler_manager()

        # Convert to internal config format
        autonomous_config = AutonomousConfig(
            enabled=config.enabled,
            training_schedule=config.training_schedule,
            timezone=config.timezone,
        )

        success = await manager.update_schedule(
            schedule_id=schedule_id,
            config=autonomous_config,
            updated_by=current_user.get("user_id"),
        )

        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Audit log
        training_audit_logger.log_config_updated(
            user=current_user,
            config_type="training_schedule",
            config_changes={
                "schedule_id": schedule_id,
                "enabled": config.enabled,
                "training_schedule": config.training_schedule,
                "timezone": config.timezone,
            },
        )

        return {"message": f"Schedule {schedule_id} updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str, current_user: dict = Depends(require_admin_user)
) -> Dict[str, str]:
    """Delete a training schedule (requires admin privileges)."""
    try:
        manager = get_scheduler_manager()
        success = await manager.delete_schedule(
            schedule_id=schedule_id, deleted_by=current_user.get("user_id")
        )

        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Audit log
        training_audit_logger.log_config_updated(
            user=current_user,
            config_type="training_schedule",
            config_changes={"schedule_id": schedule_id, "action": "deleted"},
        )

        return {"message": f"Schedule {schedule_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedules/{schedule_id}/execute")
async def execute_schedule(
    schedule_id: str, current_user: dict = Depends(require_admin_user)
) -> Dict[str, str]:
    """Manually execute a training schedule (requires admin privileges)."""
    try:
        manager = get_scheduler_manager()
        execution_id = await manager.execute_schedule(
            schedule_id=schedule_id, executed_by=current_user.get("user_id")
        )

        # Audit log
        training_audit_logger.log_training_started(
            user=current_user, training_job_id=execution_id, correlation_id=schedule_id
        )

        return {
            "execution_id": execution_id,
            "message": f"Schedule {schedule_id} execution started",
        }

    except Exception as e:
        logger.error(f"Failed to execute schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Additional endpoints for cron help
@router.get("/cron-help", response_model=Dict[str, Any])
async def get_cron_help():
    """Get help information for cron expressions."""
    return {
        "format": "minute hour day_of_month month day_of_week",
        "examples": {
            "0 2 * * *": "Daily at 2:00 AM",
            "0 */6 * * *": "Every 6 hours",
            "0 9 * * 1": "Every Monday at 9:00 AM",
            "30 14 1 * *": "First day of every month at 2:30 PM",
            "0 0 * * 0": "Every Sunday at midnight",
        },
        "special_values": {
            "*": "Any value",
            "*/n": "Every n units",
            "a-b": "Range from a to b",
            "a,b,c": "Specific values a, b, and c",
        },
        "fields": {
            "minute": "0-59",
            "hour": "0-23",
            "day_of_month": "1-31",
            "month": "1-12",
            "day_of_week": "0-7 (0 and 7 are Sunday)",
        },
    }
