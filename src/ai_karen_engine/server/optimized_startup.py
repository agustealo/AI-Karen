"""
Optimized Startup System Integration.

This module integrates all performance optimization components with the existing
codebase to provide optimized service lifecycle management, lazy loading,
async processing, and resource monitoring.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI

from ai_karen_engine.core.services.service_lifecycle_manager import ServiceLifecycleManager
from ai_karen_engine.core.runtime.lazy_loading_controller import LazyLoadingController
from ai_karen_engine.core.runtime.async_task_orchestrator import AsyncTaskOrchestrator
from ai_karen_engine.core.runtime.gpu_compute_offloader import GPUComputeOffloader
from ai_karen_engine.core.runtime.resource_monitor import ResourceMonitor
from ai_karen_engine.core.observability.performance_metrics import PerformanceMetrics
from ai_karen_engine.core.services.classified_service_registry import ClassifiedServiceRegistry
from tools.performance_auditor import PerformanceAuditor
from ai_karen_engine.config.deployment_config_manager import DeploymentConfigManager

logger = logging.getLogger(__name__)

# Global optimization components
_lifecycle_manager: Optional[ServiceLifecycleManager] = None
_lazy_controller: Optional[LazyLoadingController] = None
_task_orchestrator: Optional[AsyncTaskOrchestrator] = None
_gpu_offloader: Optional[GPUComputeOffloader] = None
_resource_monitor: Optional[ResourceMonitor] = None
_performance_metrics: Optional[PerformanceMetrics] = None
_classified_registry: Optional[ClassifiedServiceRegistry] = None
_deployment_config: Optional[DeploymentConfigManager] = None


async def initialize_optimization_components(settings: Any) -> Dict[str, Any]:
    """Initialize all performance optimization components."""
    global _lifecycle_manager, _lazy_controller, _task_orchestrator
    global _gpu_offloader, _resource_monitor, _performance_metrics
    global _classified_registry, _deployment_config
    
    logger.info("🚀 Initializing performance optimization components...")
    start_time = time.time()
    
    try:
        # Initialize deployment configuration manager
        _deployment_config = DeploymentConfigManager()
        await _deployment_config.initialize()
        
        # Get deployment profile from environment or settings
        deployment_mode = getattr(settings, 'deployment_mode', 
                                os.getenv('DEPLOYMENT_MODE', 'development'))
        
        logger.info(f"📋 Using deployment mode: {deployment_mode}")
        
        # Initialize classified service registry with deployment config
        _classified_registry = ClassifiedServiceRegistry()
        await _classified_registry.load_service_config()
        
        # Initialize performance metrics collector
        _performance_metrics = PerformanceMetrics()
        await _performance_metrics.initialize()
        
        # Initialize resource monitor
        _resource_monitor = ResourceMonitor()
        await _resource_monitor.initialize()
        
        # Initialize async task orchestrator
        _task_orchestrator = AsyncTaskOrchestrator()
        await _task_orchestrator.initialize()
        
        # Initialize GPU compute offloader if available
        _gpu_offloader = GPUComputeOffloader()
        gpu_available = await _gpu_offloader.initialize()
        
        # Initialize lazy loading controller
        _lazy_controller = LazyLoadingController()
        await _lazy_controller.initialize()
        
        # Initialize service lifecycle manager with all components
        _lifecycle_manager = ServiceLifecycleManager(
            service_registry=_classified_registry,
            lazy_controller=_lazy_controller,
            resource_monitor=_resource_monitor,
            deployment_config=_deployment_config
        )
        await _lifecycle_manager.initialize()
        
        initialization_time = time.time() - start_time
        
        # Record initialization metrics
        await _performance_metrics.record_metric(
            "system_initialization_time",
            initialization_time,
            service_name="optimization_system",
            tags={"deployment_mode": deployment_mode}
        )
        
        logger.info(f"✅ Performance optimization components initialized in {initialization_time:.2f}s")
        
        return {
            "initialization_time": initialization_time,
            "deployment_mode": deployment_mode,
            "gpu_available": gpu_available,
            "components": {
                "lifecycle_manager": _lifecycle_manager is not None,
                "lazy_controller": _lazy_controller is not None,
                "task_orchestrator": _task_orchestrator is not None,
                "gpu_offloader": _gpu_offloader is not None,
                "resource_monitor": _resource_monitor is not None,
                "performance_metrics": _performance_metrics is not None,
                "classified_registry": _classified_registry is not None,
                "deployment_config": _deployment_config is not None
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize optimization components: {e}")
        raise


async def optimized_service_startup(settings: Any) -> Dict[str, Any]:
    """Perform optimized service startup using lifecycle management."""
    if not _lifecycle_manager:
        raise RuntimeError("Optimization components not initialized")
    
    logger.info("🔧 Starting optimized service initialization...")
    start_time = time.time()
    
    try:
        # Start essential services only
        essential_services = await _lifecycle_manager.start_essential_services()
        
        # Configure lazy loading for optional services
        optional_services = await _classified_registry.get_services_by_classification("optional")
        for service_name, service_config in optional_services.items():
            await _lazy_controller.register_lazy_service(
                service_name,
                service_config.service_type,
                dependencies=service_config.dependencies
            )
        
        # Start background services with lower priority
        background_services = await _lifecycle_manager.start_background_services()
        
        startup_time = time.time() - start_time
        
        # Record startup metrics
        await _performance_metrics.record_metric(
            "optimized_startup_time",
            startup_time,
            service_name="system",
            tags={"mode": "optimized"}
        )
        
        logger.info(f"✅ Optimized service startup completed in {startup_time:.2f}s")
        logger.info(f"   • Essential services: {len(essential_services)}")
        logger.info(f"   • Lazy-loaded services: {len(optional_services)}")
        logger.info(f"   • Background services: {len(background_services)}")
        
        return {
            "startup_time": startup_time,
            "essential_services": essential_services,
            "lazy_services": list(optional_services.keys()),
            "background_services": background_services
        }
        
    except Exception as e:
        logger.error(f"❌ Optimized service startup failed: {e}")
        raise


async def initialize_performance_monitoring(settings: Any) -> None:
    """Initialize performance monitoring and alerting."""
    if not _resource_monitor or not _performance_metrics:
        logger.warning("⚠️ Performance monitoring components not available")
        return
    
    try:
        # Start resource monitoring
        await _resource_monitor.start_monitoring()
        
        # Configure performance thresholds
        thresholds = {
            "cpu_percent": getattr(settings, 'cpu_threshold', 80.0),
            "memory_percent": getattr(settings, 'memory_threshold', 85.0),
            "response_time": getattr(settings, 'response_time_threshold', 2.0)
        }
        
        await _resource_monitor.configure_thresholds(thresholds)
        
        # Start performance metrics collection
        await _performance_metrics.start_collection()
        
        logger.info("📊 Performance monitoring initialized")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize performance monitoring: {e}")


async def integrate_with_existing_logging(settings: Any) -> None:
    """Integrate performance metrics with existing logging system."""
    if not _performance_metrics:
        return
    
    try:
        # Configure metrics to use existing logging infrastructure
        log_config = {
            "log_level": getattr(settings, 'log_level', 'INFO'),
            "log_file": "logs/performance.log",
            "max_file_size": 10 * 1024 * 1024,  # 10MB
            "backup_count": 5
        }
        
        await _performance_metrics.configure_logging(log_config)
        
        logger.info("📝 Performance metrics integrated with logging system")
        
    except Exception as e:
        logger.error(f"❌ Failed to integrate with logging system: {e}")


async def run_startup_audit(settings: Any) -> Dict[str, Any]:
    """Run performance audit during startup to establish baseline."""
    try:
        auditor = PerformanceAuditor()
        await auditor.initialize()
        
        # Run startup performance audit
        audit_report = await auditor.audit_startup_performance()
        
        # Generate optimization recommendations
        recommendations = await auditor.generate_optimization_recommendations()
        
        logger.info("🔍 Startup performance audit completed")
        logger.info(f"   • Services audited: {len(audit_report.get('services', {}))}")
        logger.info(f"   • Recommendations: {len(recommendations)}")
        
        return {
            "audit_report": audit_report,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"❌ Startup audit failed: {e}")
        return {"error": str(e)}


async def cleanup_optimization_components() -> None:
    """Cleanup all optimization components during shutdown."""
    global _lifecycle_manager, _lazy_controller, _task_orchestrator
    global _gpu_offloader, _resource_monitor, _performance_metrics
    global _classified_registry, _deployment_config
    
    logger.info("🧹 Cleaning up optimization components...")
    
    cleanup_tasks = []
    
    # Shutdown components in reverse order
    if _resource_monitor:
        cleanup_tasks.append(_resource_monitor.shutdown())
    
    if _performance_metrics:
        cleanup_tasks.append(_performance_metrics.shutdown())
    
    if _task_orchestrator:
        cleanup_tasks.append(_task_orchestrator.shutdown())
    
    if _gpu_offloader:
        cleanup_tasks.append(_gpu_offloader.shutdown())
    
    if _lazy_controller:
        cleanup_tasks.append(_lazy_controller.shutdown())
    
    if _lifecycle_manager:
        cleanup_tasks.append(_lifecycle_manager.shutdown())
    
    if _classified_registry:
        cleanup_tasks.append(_classified_registry.shutdown())
    
    if _deployment_config:
        cleanup_tasks.append(_deployment_config.shutdown())
    
    # Execute all cleanup tasks concurrently
    if cleanup_tasks:
        try:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
    
    # Reset global references
    _lifecycle_manager = None
    _lazy_controller = None
    _task_orchestrator = None
    _gpu_offloader = None
    _resource_monitor = None
    _performance_metrics = None
    _classified_registry = None
    _deployment_config = None
    
    logger.info("✅ Optimization components cleanup completed")


# Dependency injection helpers for optimized components
def get_lifecycle_manager() -> Optional[ServiceLifecycleManager]:
    """Get the service lifecycle manager instance."""
    return _lifecycle_manager


def get_lazy_controller() -> Optional[LazyLoadingController]:
    """Get the lazy loading controller instance."""
    return _lazy_controller


def get_task_orchestrator() -> Optional[AsyncTaskOrchestrator]:
    """Get the async task orchestrator instance."""
    return _task_orchestrator


def get_gpu_offloader() -> Optional[GPUComputeOffloader]:
    """Get the GPU compute offloader instance."""
    return _gpu_offloader


def get_resource_monitor() -> Optional[ResourceMonitor]:
    """Get the resource monitor instance."""
    return _resource_monitor


def get_performance_metrics() -> Optional[PerformanceMetrics]:
    """Get the performance metrics instance."""
    return _performance_metrics


def get_classified_registry() -> Optional[ClassifiedServiceRegistry]:
    """Get the classified service registry instance."""
    return _classified_registry


def get_deployment_config() -> Optional[DeploymentConfigManager]:
    """Get the deployment config manager instance."""
    return _deployment_config


__all__ = [
    "initialize_optimization_components",
    "optimized_service_startup",
    "initialize_performance_monitoring",
    "integrate_with_existing_logging",
    "run_startup_audit",
    "cleanup_optimization_components",
]