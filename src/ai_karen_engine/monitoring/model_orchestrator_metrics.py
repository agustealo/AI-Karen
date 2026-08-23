"""
Model Orchestrator Metrics for Prometheus Integration.

This module provides comprehensive metrics collection for model orchestrator operations,
integrating with the existing metrics manager and following established patterns.
"""

import logging
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class ModelOperationType(Enum):
    """Types of model operations for metrics tracking."""
    DOWNLOAD = "download"
    REMOVE = "remove"
    MIGRATE = "migrate"
    ENSURE = "ensure"
    GARBAGE_COLLECT = "gc"
    LIST = "list"
    INFO = "info"
    BROWSE = "browse"
    VALIDATE = "validate"


class ModelOperationStatus(Enum):
    """Status of model operations for metrics tracking."""
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ModelMetricsContext:
    """Context for model operation metrics."""
    operation: ModelOperationType
    model_id: Optional[str] = None
    user_id: Optional[str] = None
    library: Optional[str] = None
    size_bytes: Optional[int] = None
    start_time: Optional[float] = None


class ModelOrchestratorMetrics:
    """
    Metrics collector for model orchestrator operations.
    
    Integrates with existing metrics manager to provide comprehensive
    observability for model management operations.
    """
    
    def __init__(self):
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()
        logger.debug("Model orchestrator metrics initialized")
    
    def _initialize_metrics(self):
        """Initialize all model orchestrator metrics."""
        with self.metrics_manager.safe_metrics_context():
            # Operation counters
            self.operation_total = self.metrics_manager.register_counter(
                'kari_model_operations_total',
                'Total model operations performed',
                ['operation', 'status', 'library']
            )
            
            # Operation duration
            self.operation_duration = self.metrics_manager.register_histogram(
                'kari_model_operation_duration_seconds',
                'Duration of model operations',
                ['operation', 'library'],
                buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0]
            )
            
            # Download metrics
            self.download_bytes_total = self.metrics_manager.register_counter(
                'kari_model_download_bytes_total',
                'Total bytes downloaded for models',
                ['library', 'status']
            )
            
            self.download_speed_bytes_per_second = self.metrics_manager.register_histogram(
                'kari_model_download_speed_bytes_per_second',
                'Download speed in bytes per second',
                ['library'],
                buckets=[1024, 10240, 102400, 1048576, 10485760, 104857600]  # 1KB to 100MB/s
            )
            
            # Storage metrics
            self.storage_usage_bytes = self.metrics_manager.register_gauge(
                'kari_model_storage_usage_bytes',
                'Current storage usage by library',
                ['library']
            )
            
            self.model_count = self.metrics_manager.register_gauge(
                'kari_model_count_total',
                'Total number of installed models',
                ['library', 'pinned']
            )
            
            # Registry metrics
            self.registry_operations_total = self.metrics_manager.register_counter(
                'kari_model_registry_operations_total',
                'Total registry operations',
                ['operation', 'status']
            )
            
            self.registry_integrity_checks_total = self.metrics_manager.register_counter(
                'kari_model_registry_integrity_checks_total',
                'Total registry integrity checks',
                ['status']
            )
            
            # Error metrics
            self.operation_errors_total = self.metrics_manager.register_counter(
                'kari_model_operation_errors_total',
                'Total operation errors by type',
                ['operation', 'error_type', 'library']
            )
            
            # License metrics
            self.license_acceptances_total = self.metrics_manager.register_counter(
                'kari_model_license_acceptances_total',
                'Total license acceptances',
                ['license_type', 'model_owner']
            )
            
            # Garbage collection metrics
            self.gc_operations_total = self.metrics_manager.register_counter(
                'kari_model_gc_operations_total',
                'Total garbage collection operations',
                ['trigger', 'status']
            )
            
            self.gc_freed_bytes_total = self.metrics_manager.register_counter(
                'kari_model_gc_freed_bytes_total',
                'Total bytes freed by garbage collection',
                ['library']
            )
            
            # Migration metrics
            self.migration_operations_total = self.metrics_manager.register_counter(
                'kari_model_migration_operations_total',
                'Total migration operations',
                ['migration_type', 'status']
            )
            
            self.migration_models_processed = self.metrics_manager.register_counter(
                'kari_model_migration_models_processed_total',
                'Total models processed during migration',
                ['migration_type', 'status']
            )
            
            # Compatibility metrics
            self.compatibility_checks_total = self.metrics_manager.register_counter(
                'kari_model_compatibility_checks_total',
                'Total compatibility checks performed',
                ['check_type', 'result']
            )
            
            # API metrics
            self.api_requests_total = self.metrics_manager.register_counter(
                'kari_model_api_requests_total',
                'Total model API requests',
                ['endpoint', 'method', 'status']
            )
            
            self.api_request_duration = self.metrics_manager.register_histogram(
                'kari_model_api_request_duration_seconds',
                'Model API request duration',
                ['endpoint', 'method']
            )
            
            # WebSocket metrics
            self.websocket_connections = self.metrics_manager.register_gauge(
                'kari_model_websocket_connections_active',
                'Active WebSocket connections for model operations',
                ['operation_type']
            )
            
            self.websocket_messages_total = self.metrics_manager.register_counter(
                'kari_model_websocket_messages_total',
                'Total WebSocket messages sent',
                ['message_type', 'operation']
            )
    
    def record_operation_start(self, context: ModelMetricsContext) -> ModelMetricsContext:
        """Record the start of a model operation."""
        context.start_time = time.time()
        logger.debug(f"Started tracking operation: {context.operation.value}")
        return context
    
    def record_operation_complete(
        self,
        context: ModelMetricsContext,
        status: ModelOperationStatus,
        error_type: Optional[str] = None
    ):
        """Record the completion of a model operation."""
        try:
            # Calculate duration
            duration = time.time() - (context.start_time or time.time())
            
            # Record operation metrics
            self.operation_total.labels(
                operation=context.operation.value,
                status=status.value,
                library=context.library or "unknown"
            ).inc()
            
            self.operation_duration.labels(
                operation=context.operation.value,
                library=context.library or "unknown"
            ).observe(duration)
            
            # Record errors if applicable
            if status == ModelOperationStatus.FAILURE and error_type:
                self.operation_errors_total.labels(
                    operation=context.operation.value,
                    error_type=error_type,
                    library=context.library or "unknown"
                ).inc()
            
            logger.debug(
                f"Recorded operation completion: {context.operation.value} "
                f"({status.value}) in {duration:.2f}s"
            )
            
        except Exception as e:
            logger.error(f"Error recording operation metrics: {e}")
    
    def record_download_metrics(
        self,
        library: str,
        bytes_downloaded: int,
        duration_seconds: float,
        status: ModelOperationStatus
    ):
        """Record download-specific metrics."""
        try:
            # Record bytes downloaded
            self.download_bytes_total.labels(
                library=library,
                status=status.value
            ).inc(bytes_downloaded)
            
            # Calculate and record download speed
            if duration_seconds > 0:
                speed_bps = bytes_downloaded / duration_seconds
                self.download_speed_bytes_per_second.labels(
                    library=library
                ).observe(speed_bps)
            
            logger.debug(
                f"Recorded download metrics: {bytes_downloaded} bytes "
                f"in {duration_seconds:.2f}s for {library}"
            )
            
        except Exception as e:
            logger.error(f"Error recording download metrics: {e}")
    
    def update_storage_metrics(self, storage_by_library: Dict[str, int]):
        """Update storage usage metrics."""
        try:
            for library, bytes_used in storage_by_library.items():
                self.storage_usage_bytes.labels(library=library).set(bytes_used)
            
            logger.debug(f"Updated storage metrics for {len(storage_by_library)} libraries")
            
        except Exception as e:
            logger.error(f"Error updating storage metrics: {e}")
    
    def update_model_count_metrics(self, counts_by_library: Dict[str, Dict[str, int]]):
        """Update model count metrics."""
        try:
            for library, counts in counts_by_library.items():
                for pinned_status, count in counts.items():
                    self.model_count.labels(
                        library=library,
                        pinned=pinned_status
                    ).set(count)
            
            logger.debug(f"Updated model count metrics for {len(counts_by_library)} libraries")
            
        except Exception as e:
            logger.error(f"Error updating model count metrics: {e}")
    
    def record_registry_operation(self, operation: str, status: ModelOperationStatus):
        """Record registry operation metrics."""
        try:
            self.registry_operations_total.labels(
                operation=operation,
                status=status.value
            ).inc()
            
            logger.debug(f"Recorded registry operation: {operation} ({status.value})")
            
        except Exception as e:
            logger.error(f"Error recording registry operation metrics: {e}")
    
    def record_integrity_check(self, status: ModelOperationStatus):
        """Record registry integrity check metrics."""
        try:
            self.registry_integrity_checks_total.labels(
                status=status.value
            ).inc()
            
            logger.debug(f"Recorded integrity check: {status.value}")
            
        except Exception as e:
            logger.error(f"Error recording integrity check metrics: {e}")
    
    def record_license_acceptance(self, license_type: str, model_owner: str):
        """Record license acceptance metrics."""
        try:
            self.license_acceptances_total.labels(
                license_type=license_type,
                model_owner=model_owner
            ).inc()
            
            logger.debug(f"Recorded license acceptance: {license_type} for {model_owner}")
            
        except Exception as e:
            logger.error(f"Error recording license acceptance metrics: {e}")
    
    def record_gc_operation(
        self,
        trigger: str,
        status: ModelOperationStatus,
        freed_bytes_by_library: Optional[Dict[str, int]] = None
    ):
        """Record garbage collection metrics."""
        try:
            self.gc_operations_total.labels(
                trigger=trigger,
                status=status.value
            ).inc()
            
            if freed_bytes_by_library and status == ModelOperationStatus.SUCCESS:
                for library, freed_bytes in freed_bytes_by_library.items():
                    self.gc_freed_bytes_total.labels(library=library).inc(freed_bytes)
            
            logger.debug(f"Recorded GC operation: {trigger} ({status.value})")
            
        except Exception as e:
            logger.error(f"Error recording GC metrics: {e}")
    
    def record_migration_operation(
        self,
        migration_type: str,
        status: ModelOperationStatus,
        models_processed: int = 0
    ):
        """Record migration operation metrics."""
        try:
            self.migration_operations_total.labels(
                migration_type=migration_type,
                status=status.value
            ).inc()
            
            if models_processed > 0:
                self.migration_models_processed.labels(
                    migration_type=migration_type,
                    status=status.value
                ).inc(models_processed)
            
            logger.debug(
                f"Recorded migration operation: {migration_type} ({status.value}) "
                f"- {models_processed} models"
            )
            
        except Exception as e:
            logger.error(f"Error recording migration metrics: {e}")
    
    def record_compatibility_check(self, check_type: str, result: str):
        """Record compatibility check metrics."""
        try:
            self.compatibility_checks_total.labels(
                check_type=check_type,
                result=result
            ).inc()
            
            logger.debug(f"Recorded compatibility check: {check_type} -> {result}")
            
        except Exception as e:
            logger.error(f"Error recording compatibility check metrics: {e}")
    
    def record_api_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_seconds: float
    ):
        """Record API request metrics."""
        try:
            status = "success" if 200 <= status_code < 400 else "error"
            
            self.api_requests_total.labels(
                endpoint=endpoint,
                method=method,
                status=status
            ).inc()
            
            self.api_request_duration.labels(
                endpoint=endpoint,
                method=method
            ).observe(duration_seconds)
            
            logger.debug(
                f"Recorded API request: {method} {endpoint} "
                f"({status_code}) in {duration_seconds:.3f}s"
            )
            
        except Exception as e:
            logger.error(f"Error recording API request metrics: {e}")
    
    def update_websocket_connections(self, operation_type: str, count: int):
        """Update WebSocket connection metrics."""
        try:
            self.websocket_connections.labels(
                operation_type=operation_type
            ).set(count)
            
            logger.debug(f"Updated WebSocket connections: {operation_type} = {count}")
            
        except Exception as e:
            logger.error(f"Error updating WebSocket connection metrics: {e}")
    
    def record_websocket_message(self, message_type: str, operation: str):
        """Record WebSocket message metrics."""
        try:
            self.websocket_messages_total.labels(
                message_type=message_type,
                operation=operation
            ).inc()
            
            logger.debug(f"Recorded WebSocket message: {message_type} for {operation}")
            
        except Exception as e:
            logger.error(f"Error recording WebSocket message metrics: {e}")
    
    @contextmanager
    def operation_timer(self, context: ModelMetricsContext):
        """Context manager for timing operations."""
        context = self.record_operation_start(context)
        try:
            yield context
            self.record_operation_complete(context, ModelOperationStatus.SUCCESS)
        except Exception as e:
            error_type = type(e).__name__
            self.record_operation_complete(
                context, 
                ModelOperationStatus.FAILURE, 
                error_type
            )
            raise
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of current metrics state."""
        return {
            "metrics_manager_info": self.metrics_manager.get_metrics_info(),
            "registered_metrics": [
                "kari_model_operations_total",
                "kari_model_operation_duration_seconds",
                "kari_model_download_bytes_total",
                "kari_model_download_speed_bytes_per_second",
                "kari_model_storage_usage_bytes",
                "kari_model_count_total",
                "kari_model_registry_operations_total",
                "kari_model_registry_integrity_checks_total",
                "kari_model_operation_errors_total",
                "kari_model_license_acceptances_total",
                "kari_model_gc_operations_total",
                "kari_model_gc_freed_bytes_total",
                "kari_model_migration_operations_total",
                "kari_model_migration_models_processed_total",
                "kari_model_compatibility_checks_total",
                "kari_model_api_requests_total",
                "kari_model_api_request_duration_seconds",
                "kari_model_websocket_connections_active",
                "kari_model_websocket_messages_total"
            ]
        }


# Global metrics instance
_model_orchestrator_metrics: Optional[ModelOrchestratorMetrics] = None


def get_model_orchestrator_metrics() -> ModelOrchestratorMetrics:
    """Get the global model orchestrator metrics instance."""
    global _model_orchestrator_metrics
    if _model_orchestrator_metrics is None:
        _model_orchestrator_metrics = ModelOrchestratorMetrics()
    return _model_orchestrator_metrics


def create_operation_context(
    operation: ModelOperationType,
    model_id: Optional[str] = None,
    user_id: Optional[str] = None,
    library: Optional[str] = None,
    size_bytes: Optional[int] = None
) -> ModelMetricsContext:
    """Create a metrics context for a model operation."""
    return ModelMetricsContext(
        operation=operation,
        model_id=model_id,
        user_id=user_id,
        library=library,
        size_bytes=size_bytes
    )