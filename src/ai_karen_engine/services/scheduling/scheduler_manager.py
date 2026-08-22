"""
Cron-based autonomous training scheduler for the Response Core orchestrator.

This module implements a comprehensive scheduling system for autonomous learning cycles,
including configurable training schedules, quality thresholds, safety controls, and
notification systems for training completion and failures.
"""

import asyncio
import logging
import uuid
import json
import smtplib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union
from pathlib import Path
import threading
import time

# Email imports with error handling
try:
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    MIMEText = None
    MIMEMultipart = None

try:
    from croniter import croniter
except ImportError:
    croniter = None
    # Note: croniter not available - cron scheduling will be disabled

from ai_karen_engine.learning.autonomous_learner import AutonomousLearner, LearningCycleResult
from ai_karen_engine.core.memory.memory_service import WebUIMemoryService
from ai_karen_engine.core.runtime.resilience import get_feature_flags

logger = logging.getLogger(__name__)


class ScheduleStatus(str, Enum):
    """Status of scheduled training jobs."""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    FAILED = "failed"
    COMPLETED = "completed"


class NotificationType(str, Enum):
    """Types of notifications."""
    EMAIL = "email"
    WEBHOOK = "webhook"
    LOG = "log"
    MEMORY = "memory"


class SafetyLevel(str, Enum):
    """Safety levels for autonomous training."""
    STRICT = "strict"      # Maximum safety checks
    MODERATE = "moderate"  # Balanced safety and autonomy
    PERMISSIVE = "permissive"  # Minimal safety checks


@dataclass
class NotificationConfig:
    """Configuration for notifications."""
    enabled: bool = True
    types: List[NotificationType] = field(default_factory=lambda: [NotificationType.LOG])
    
    # Email configuration
    email_smtp_host: Optional[str] = None
    email_smtp_port: int = 587
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_recipients: List[str] = field(default_factory=list)
    email_use_tls: bool = True
    
    # Webhook configuration
    webhook_url: Optional[str] = None
    webhook_headers: Dict[str, str] = field(default_factory=dict)
    webhook_timeout: int = 30
    
    # Memory storage configuration
    memory_tenant_id: Optional[str] = None
    memory_importance_score: int = 8
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class SafetyControls:
    """Safety controls for autonomous training."""
    level: SafetyLevel = SafetyLevel.MODERATE
    
    # Data quality controls
    min_data_threshold: int = 100
    max_data_threshold: int = 10000
    quality_threshold: float = 0.7
    
    # Training controls
    max_training_time_minutes: int = 60
    validation_threshold: float = 0.85
    rollback_on_degradation: bool = True
    
    # Resource controls
    max_memory_usage_mb: int = 2048
    max_cpu_usage_percent: float = 80.0
    
    # Failure controls
    max_consecutive_failures: int = 3
    failure_cooldown_hours: int = 24
    
    # Backup controls
    backup_before_training: bool = True
    max_backup_retention_days: int = 30
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class AutonomousConfig:
    """Configuration for autonomous training mode."""
    enabled: bool = False
    training_schedule: str = "0 2 * * *"  # Daily at 2 AM
    timezone: str = "UTC"
    
    # Quality thresholds
    min_data_threshold: int = 100
    quality_threshold: float = 0.7
    validation_threshold: float = 0.85
    
    # Safety controls
    safety_controls: SafetyControls = field(default_factory=SafetyControls)
    
    # Notification settings
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    
    # Advanced settings
    max_training_time: int = 3600  # seconds
    backup_models: bool = True
    auto_rollback: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        result = asdict(self)
        result["safety_controls"] = self.safety_controls.to_dict()
        result["notifications"] = self.notifications.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutonomousConfig":
        """Create from dictionary."""
        safety_data = data.pop("safety_controls", {})
        notification_data = data.pop("notifications", {})
        
        config = cls(**data)
        config.safety_controls = SafetyControls(**safety_data)
        config.notifications = NotificationConfig(**notification_data)
        
        return config


@dataclass
class ScheduleInfo:
    """Information about a scheduled training job."""
    schedule_id: str
    tenant_id: str
    name: str
    description: str
    cron_expression: str
    timezone: str = "UTC"
    
    # Configuration
    autonomous_config: AutonomousConfig = field(default_factory=AutonomousConfig)
    
    # Status tracking
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_result: Optional[str] = None  # JSON string of last LearningCycleResult
    
    # Statistics
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    consecutive_failures: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        result = asdict(self)
        result["autonomous_config"] = self.autonomous_config.to_dict()
        result["created_at"] = self.created_at.isoformat()
        result["last_run"] = self.last_run.isoformat() if self.last_run else None
        result["next_run"] = self.next_run.isoformat() if self.next_run else None
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleInfo":
        """Create from dictionary."""
        config_data = data.pop("autonomous_config", {})
        
        # Parse datetime fields
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "last_run" in data and data["last_run"]:
            data["last_run"] = datetime.fromisoformat(data["last_run"])
        if "next_run" in data and data["next_run"]:
            data["next_run"] = datetime.fromisoformat(data["next_run"])
        
        schedule = cls(**data)
        schedule.autonomous_config = AutonomousConfig.from_dict(config_data)
        
        return schedule


class NotificationManager:
    """Manages notifications for training events."""
    
    def __init__(self, memory_service: Optional[WebUIMemoryService] = None):
        self.memory_service = memory_service
        
    async def send_notification(
        self,
        config: NotificationConfig,
        event_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ):
        """Send notification through configured channels."""
        try:
            for notification_type in config.types:
                if notification_type == NotificationType.LOG:
                    await self._send_log_notification(event_type, title, message, data)
                elif notification_type == NotificationType.EMAIL:
                    await self._send_email_notification(config, title, message, data)
                elif notification_type == NotificationType.WEBHOOK:
                    await self._send_webhook_notification(config, event_type, title, message, data)
                elif notification_type == NotificationType.MEMORY:
                    await self._send_memory_notification(config, event_type, title, message, data)
                    
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    async def _send_log_notification(
        self, 
        event_type: str, 
        title: str, 
        message: str, 
        data: Optional[Dict[str, Any]]
    ):
        """Send log notification."""
        log_message = f"[{event_type.upper()}] {title}: {message}"
        if data:
            log_message += f" | Data: {json.dumps(data, default=str)}"
        
        if event_type in ["training_failed", "schedule_failed"]:
            logger.error(log_message)
        elif event_type in ["training_completed", "schedule_completed"]:
            logger.info(log_message)
        else:
            logger.debug(log_message)
    
    async def _send_email_notification(
        self,
        config: NotificationConfig,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]]
    ):
        """Send email notification."""
        if not EMAIL_AVAILABLE:
            logger.warning("Email functionality not available - email modules not imported")
            return
            
        if not config.email_recipients or not config.email_smtp_host:
            logger.warning("Email notification configured but missing recipients or SMTP host")
            return
        
        try:
            msg = MIMEMultipart()
            msg['From'] = config.email_username or "karen-ai@localhost"
            msg['To'] = ", ".join(config.email_recipients)
            msg['Subject'] = f"Karen AI Training Notification: {title}"
            
            body = f"{message}\n\n"
            if data:
                body += f"Additional Data:\n{json.dumps(data, indent=2, default=str)}"
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(config.email_smtp_host, config.email_smtp_port)
            if config.email_use_tls:
                server.starttls()
            if config.email_username and config.email_password:
                server.login(config.email_username, config.email_password)
            
            server.send_message(msg)
            server.quit()
            
            logger.info(f"Email notification sent to {len(config.email_recipients)} recipients")
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
    
    async def _send_webhook_notification(
        self,
        config: NotificationConfig,
        event_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]]
    ):
        """Send webhook notification."""
        if not config.webhook_url:
            return
        
        try:
            import aiohttp
            
            payload = {
                "event_type": event_type,
                "title": title,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data or {}
            }
            
            headers = {"Content-Type": "application/json"}
            headers.update(config.webhook_headers)
            
            timeout = aiohttp.ClientTimeout(total=config.webhook_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    config.webhook_url,
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        logger.info("Webhook notification sent successfully")
                    else:
                        logger.warning(f"Webhook notification failed with status {response.status}")
                        
        except ImportError:
            logger.warning("aiohttp not available for webhook notifications")
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
    
    async def _send_memory_notification(
        self,
        config: NotificationConfig,
        event_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]]
    ):
        """Send memory notification."""
        if not self.memory_service or not config.memory_tenant_id:
            return
        
        try:
            from ai_karen_engine.core.memory.memory_service import MemoryType, UISource
            
            content = f"Training Notification: {title}\n\n{message}"
            
            await self.memory_service.store_web_ui_memory(
                tenant_id=config.memory_tenant_id,
                content=content,
                user_id="system",
                ui_source=UISource.API,
                memory_type=MemoryType.INSIGHT,
                tags=["autonomous_training", "notification", event_type],
                importance_score=config.memory_importance_score,
                ai_generated=True,
                metadata={
                    "event_type": event_type,
                    "title": title,
                    "notification_data": data or {}
                }
            )
            
            logger.info("Memory notification stored successfully")
            
        except Exception as e:
            logger.error(f"Failed to send memory notification: {e}")


class SchedulerManager:
    """
    Manages cron-based autonomous training schedules.
    
    This class provides comprehensive scheduling capabilities for autonomous learning cycles,
    including configurable training schedules, quality thresholds, safety controls, and
    notification systems for training completion and failures.
    """
    
    def __init__(
        self,
        autonomous_learner: AutonomousLearner,
        memory_service: Optional[WebUIMemoryService] = None,
        storage_path: Optional[Path] = None
    ):
        self.autonomous_learner = autonomous_learner
        self.memory_service = memory_service
        self.notification_manager = NotificationManager(memory_service)
        
        # Storage for schedule persistence
        self.storage_path = storage_path or Path("./data/scheduler")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.schedules_file = self.storage_path / "schedules.json"
        
        # In-memory schedule tracking
        self.schedules: Dict[str, ScheduleInfo] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.scheduler_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Load existing schedules
        self._load_schedules()
        
        # Safety monitoring
        self.resource_monitor = ResourceMonitor()
        
    def create_training_schedule(
        self,
        tenant_id: str,
        name: str,
        cron_expression: str,
        config: AutonomousConfig,
        description: str = ""
    ) -> str:
        """Create a new training schedule."""
        try:
            # Validate cron expression
            if croniter is None:
                raise RuntimeError("croniter not available - cannot create cron schedules")
            
            if not croniter.is_valid(cron_expression):
                raise ValueError(f"Invalid cron expression: {cron_expression}")
            
            # Generate schedule ID
            schedule_id = str(uuid.uuid4())
            
            # Calculate next run time
            cron = croniter(cron_expression, datetime.utcnow())
            next_run = cron.get_next(datetime)
            
            # Create schedule info
            schedule = ScheduleInfo(
                schedule_id=schedule_id,
                tenant_id=tenant_id,
                name=name,
                description=description,
                cron_expression=cron_expression,
                timezone=config.timezone,
                autonomous_config=config,
                next_run=next_run
            )
            
            # Store schedule
            self.schedules[schedule_id] = schedule
            self._save_schedules()
            
            logger.info(f"Created training schedule: {name} ({schedule_id})")
            return schedule_id
            
        except Exception as e:
            logger.error(f"Failed to create training schedule: {e}")
            raise
    
    def update_schedule(self, schedule_id: str, **updates) -> bool:
        """Update an existing schedule."""
        try:
            if schedule_id not in self.schedules:
                raise ValueError(f"Schedule not found: {schedule_id}")
            
            schedule = self.schedules[schedule_id]
            
            # Update fields
            for key, value in updates.items():
                if hasattr(schedule, key):
                    setattr(schedule, key, value)
                elif key == "autonomous_config" and isinstance(value, dict):
                    schedule.autonomous_config = AutonomousConfig.from_dict(value)
            
            # Recalculate next run if cron expression changed
            if "cron_expression" in updates:
                if croniter is None:
                    raise RuntimeError("croniter not available")
                
                if not croniter.is_valid(schedule.cron_expression):
                    raise ValueError(f"Invalid cron expression: {schedule.cron_expression}")
                
                cron = croniter(schedule.cron_expression, datetime.utcnow())
                schedule.next_run = cron.get_next(datetime)
            
            self._save_schedules()
            logger.info(f"Updated schedule: {schedule_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update schedule {schedule_id}: {e}")
            return False
    
    def pause_schedule(self, schedule_id: str) -> bool:
        """Pause a schedule."""
        try:
            if schedule_id not in self.schedules:
                raise ValueError(f"Schedule not found: {schedule_id}")
            
            schedule = self.schedules[schedule_id]
            schedule.status = ScheduleStatus.PAUSED
            
            # Cancel running task if any
            if schedule_id in self.running_tasks:
                self.running_tasks[schedule_id].cancel()
                del self.running_tasks[schedule_id]
            
            self._save_schedules()
            logger.info(f"Paused schedule: {schedule_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to pause schedule {schedule_id}: {e}")
            return False
    
    def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused schedule."""
        try:
            if schedule_id not in self.schedules:
                raise ValueError(f"Schedule not found: {schedule_id}")
            
            schedule = self.schedules[schedule_id]
            if schedule.status != ScheduleStatus.PAUSED:
                raise ValueError(f"Schedule is not paused: {schedule_id}")
            
            schedule.status = ScheduleStatus.ACTIVE
            
            # Recalculate next run
            if croniter is not None:
                cron = croniter(schedule.cron_expression, datetime.utcnow())
                schedule.next_run = cron.get_next(datetime)
            
            self._save_schedules()
            logger.info(f"Resumed schedule: {schedule_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to resume schedule {schedule_id}: {e}")
            return False
    
    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        try:
            if schedule_id not in self.schedules:
                raise ValueError(f"Schedule not found: {schedule_id}")
            
            # Cancel running task if any
            if schedule_id in self.running_tasks:
                self.running_tasks[schedule_id].cancel()
                del self.running_tasks[schedule_id]
            
            # Remove schedule
            del self.schedules[schedule_id]
            self._save_schedules()
            
            logger.info(f"Deleted schedule: {schedule_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete schedule {schedule_id}: {e}")
            return False
    
    def get_schedule_status(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a schedule."""
        try:
            if schedule_id not in self.schedules:
                return None
            
            schedule = self.schedules[schedule_id]
            
            status = {
                "schedule_id": schedule_id,
                "name": schedule.name,
                "status": schedule.status.value,
                "cron_expression": schedule.cron_expression,
                "next_run": schedule.next_run.isoformat() if schedule.next_run else None,
                "last_run": schedule.last_run.isoformat() if schedule.last_run else None,
                "total_runs": schedule.total_runs,
                "successful_runs": schedule.successful_runs,
                "failed_runs": schedule.failed_runs,
                "consecutive_failures": schedule.consecutive_failures,
                "is_running": schedule_id in self.running_tasks
            }
            
            # Add last result if available
            if schedule.last_result:
                try:
                    status["last_result"] = json.loads(schedule.last_result)
                except json.JSONDecodeError:
                    status["last_result"] = {"error": "Failed to parse last result"}
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get schedule status {schedule_id}: {e}")
            return None
    
    def list_schedules(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all schedules, optionally filtered by tenant."""
        try:
            schedules = []
            for schedule in self.schedules.values():
                if tenant_id is None or schedule.tenant_id == tenant_id:
                    status = self.get_schedule_status(schedule.schedule_id)
                    if status:
                        schedules.append(status)
            
            return schedules
            
        except Exception as e:
            logger.error(f"Failed to list schedules: {e}")
            return []
    
    async def start_scheduler(self):
        """Start the scheduler background task."""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler started")
    
    async def stop_scheduler(self):
        """Stop the scheduler and cancel all running tasks."""
        self.running = False
        
        # Cancel scheduler task
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all running training tasks
        for task in self.running_tasks.values():
            task.cancel()
        
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks.values(), return_exceptions=True)
        
        self.running_tasks.clear()
        logger.info("Scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop that checks for due schedules."""
        while self.running:
            try:
                current_time = datetime.utcnow()
                
                for schedule_id, schedule in self.schedules.items():
                    # Skip if not active or already running
                    if (schedule.status != ScheduleStatus.ACTIVE or 
                        schedule_id in self.running_tasks):
                        continue
                    
                    # Check if schedule is due
                    if schedule.next_run and current_time >= schedule.next_run:
                        # Check safety controls before starting
                        if await self._check_safety_controls(schedule):
                            # Start training task
                            task = asyncio.create_task(
                                self._execute_training(schedule_id, schedule)
                            )
                            self.running_tasks[schedule_id] = task
                            
                            # Calculate next run time
                            if croniter is not None:
                                cron = croniter(schedule.cron_expression, current_time)
                                schedule.next_run = cron.get_next(datetime)
                                self._save_schedules()
                        else:
                            logger.warning(f"Safety controls failed for schedule {schedule_id}")
                            schedule.consecutive_failures += 1
                            self._save_schedules()
                
                # Clean up completed tasks
                completed_tasks = []
                for schedule_id, task in self.running_tasks.items():
                    if task.done():
                        completed_tasks.append(schedule_id)
                
                for schedule_id in completed_tasks:
                    del self.running_tasks[schedule_id]
                
                # Sleep for 60 seconds before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)
    
    async def _check_safety_controls(self, schedule: ScheduleInfo) -> bool:
        """Check safety controls before starting training."""
        try:
            safety = schedule.autonomous_config.safety_controls
            
            # Check consecutive failures
            if schedule.consecutive_failures >= safety.max_consecutive_failures:
                # Check if cooldown period has passed
                if schedule.last_run:
                    cooldown_period = timedelta(hours=safety.failure_cooldown_hours)
                    if datetime.utcnow() - schedule.last_run < cooldown_period:
                        logger.warning(f"Schedule {schedule.schedule_id} in failure cooldown")
                        return False
                else:
                    logger.warning(f"Schedule {schedule.schedule_id} has too many consecutive failures")
                    return False
            
            # Check resource usage
            resource_usage = await self.resource_monitor.get_current_usage()
            
            if resource_usage["memory_mb"] > safety.max_memory_usage_mb:
                logger.warning(f"Memory usage too high: {resource_usage['memory_mb']}MB")
                return False
            
            if resource_usage["cpu_percent"] > safety.max_cpu_usage_percent:
                logger.warning(f"CPU usage too high: {resource_usage['cpu_percent']}%")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking safety controls: {e}")
            return False
    
    async def _execute_training(self, schedule_id: str, schedule: ScheduleInfo):
        """Execute a training cycle for a schedule."""
        if not get_feature_flags().is_enabled("autonomous_learning_enabled", tenant_id=schedule.tenant_id):
            schedule.last_result = json.dumps({
                "error": "autonomous_learning_enabled feature flag is disabled",
                "status": "skipped",
                "timestamp": datetime.utcnow().isoformat()
            })
            self._save_schedules()
            return
        
        try:
            # Send start notification
            await self.notification_manager.send_notification(
                schedule.autonomous_config.notifications,
                "training_started",
                f"Training Started: {schedule.name}",
                f"Autonomous training cycle started for schedule '{schedule.name}'",
                {"schedule_id": schedule_id, "tenant_id": schedule.tenant_id}
            )
            
            # Execute learning cycle
            result = await self.autonomous_learner.trigger_learning_cycle(
                tenant_id=schedule.tenant_id,
                force_training=False
            )
            
            # Update schedule with result
            schedule.last_result = json.dumps(result.to_dict(), default=str)
            
            if result.status.value == "completed" and result.model_improved:
                schedule.successful_runs += 1
                schedule.consecutive_failures = 0
                
                # Send success notification
                await self.notification_manager.send_notification(
                    schedule.autonomous_config.notifications,
                    "training_completed",
                    f"Training Completed: {schedule.name}",
                    f"Training cycle completed successfully. Model improved: {result.model_improved}",
                    {
                        "schedule_id": schedule_id,
                        "tenant_id": schedule.tenant_id,
                        "result": result.to_dict()
                    }
                )
                
            else:
                schedule.failed_runs += 1
                schedule.consecutive_failures += 1
                
                # Send failure notification
                await self.notification_manager.send_notification(
                    schedule.autonomous_config.notifications,
                    "training_failed",
                    f"Training Failed: {schedule.name}",
                    f"Training cycle failed or did not improve model. Status: {result.status.value}",
                    {
                        "schedule_id": schedule_id,
                        "tenant_id": schedule.tenant_id,
                        "result": result.to_dict()
                    }
                )
            
        except Exception as e:
            schedule.failed_runs += 1
            schedule.consecutive_failures += 1
            schedule.last_result = json.dumps({
                "error": str(e),
                "status": "failed",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Send error notification
            await self.notification_manager.send_notification(
                schedule.autonomous_config.notifications,
                "training_error",
                f"Training Error: {schedule.name}",
                f"Training cycle encountered an error: {str(e)}",
                {
                    "schedule_id": schedule_id,
                    "tenant_id": schedule.tenant_id,
                    "error": str(e)
                }
            )
            
            logger.error(f"Training execution failed for schedule {schedule_id}: {e}")
        
        finally:
            # Save updated schedule
            self._save_schedules()
    
    def _load_schedules(self):
        """Load schedules from storage."""
        try:
            if self.schedules_file.exists():
                with open(self.schedules_file, 'r') as f:
                    data = json.load(f)
                
                for schedule_data in data.get("schedules", []):
                    schedule = ScheduleInfo.from_dict(schedule_data)
                    self.schedules[schedule.schedule_id] = schedule
                
                logger.info(f"Loaded {len(self.schedules)} schedules from storage")
            
        except Exception as e:
            logger.error(f"Failed to load schedules: {e}")
    
    def _save_schedules(self):
        """Save schedules to storage."""
        try:
            data = {
                "schedules": [schedule.to_dict() for schedule in self.schedules.values()],
                "last_updated": datetime.utcnow().isoformat()
            }
            
            with open(self.schedules_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            logger.error(f"Failed to save schedules: {e}")


class ResourceMonitor:
    """Monitors system resources for safety controls."""
    
    def __init__(self):
        self.last_check = None
        self.cached_usage = None
        self.cache_duration = timedelta(seconds=30)
    
    async def get_current_usage(self) -> Dict[str, float]:
        """Get current system resource usage."""
        try:
            # Use cached result if recent
            if (self.cached_usage and self.last_check and 
                datetime.utcnow() - self.last_check < self.cache_duration):
                return self.cached_usage
            
            # Get memory usage
            try:
                import psutil
                memory = psutil.virtual_memory()
                cpu_percent = psutil.cpu_percent(interval=1)
                
                usage = {
                    "memory_mb": memory.used / (1024 * 1024),
                    "memory_percent": memory.percent,
                    "cpu_percent": cpu_percent
                }
            except ImportError:
                # Fallback if psutil not available
                usage = {
                    "memory_mb": 1024,  # Assume 1GB
                    "memory_percent": 50.0,
                    "cpu_percent": 25.0
                }
            
            self.cached_usage = usage
            self.last_check = datetime.utcnow()
            
            return usage
            
        except Exception as e:
            logger.error(f"Failed to get resource usage: {e}")
            return {
                "memory_mb": 0,
                "memory_percent": 0,
                "cpu_percent": 0
            }
