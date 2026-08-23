"""
API routes for performance monitoring and metrics.
"""

# Force type checker refresh

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Depends, Response
try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field

from ai_karen_engine.core.observability.performance_metrics import (
    get_performance_monitoring_system,
    PerformanceMetric,
    MetricType,
    AlertSeverity
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class MetricRequest(BaseModel):
    """Request model for creating custom metrics."""
    name: str
    value: float
    metric_type: str = "gauge"
    service_name: str
    tags: Dict[str, str] = Field(default_factory=dict)
    unit: str = ""
    description: str = ""

    model_config = ConfigDict(extra="forbid")


class BenchmarkRequest(BaseModel):
    """Request model for creating benchmarks."""
    name: str
    duration_minutes: int = 60
    services: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")


class ComparisonRequest(BaseModel):
    """Request model for benchmark comparisons."""
    baseline_name: str
    duration_minutes: int = 60

    model_config = ConfigDict(extra="forbid")


@router.get("/dashboard")
async def get_dashboard():
    """Get real-time performance dashboard data."""
    try:
        system = get_performance_monitoring_system()
        dashboard_data = await system.get_dashboard_data()
        return {
            "status": "success",
            "data": dashboard_data
        }
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_metrics(
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    hours: int = Query(1, description="Hours of data to retrieve", ge=1, le=168),
    limit: int = Query(1000, description="Maximum number of metrics", ge=1, le=10000)
):
    """Get performance metrics with filtering."""
    try:
        system = get_performance_monitoring_system()
        
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        metrics = await system.storage.get_metrics(
            metric_name=metric_name,
            service_name=service_name,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        return {
            "status": "success",
            "data": {
                "metrics": [metric.to_dict() for metric in metrics],
                "count": len(metrics),
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat()
                }
            }
        }
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/metrics")
async def create_metric(metric: MetricRequest):
    """Create a custom performance metric."""
    try:
        system = get_performance_monitoring_system()
        
        # Validate metric type
        try:
            metric_type = MetricType(metric.metric_type.lower())
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid metric type: {metric.metric_type}"
            )
        
        # Create metric
        perf_metric = PerformanceMetric(
            name=metric.name,
            value=metric.value,
            metric_type=metric_type,
            timestamp=datetime.now(),
            service_name=metric.service_name,
            tags=metric.tags,
            unit=metric.unit,
            description=metric.description
        )
        
        await system.storage.store_metric(perf_metric)
        
        return {
            "status": "success",
            "message": "Metric created successfully",
            "data": perf_metric.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating metric: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system")
async def get_system_metrics():
    """Get current system performance metrics."""
    try:
        system = get_performance_monitoring_system()
        
        # Collect current system metrics
        system_metrics = await system.collector.collect_system_metrics()
        
        return {
            "status": "success",
            "data": {
                "timestamp": system_metrics.timestamp.isoformat(),
                "cpu_percent": system_metrics.cpu_percent,
                "memory": {
                    "usage_bytes": system_metrics.memory_usage,
                    "usage_percent": system_metrics.memory_percent
                },
                "disk": {
                    "usage_bytes": system_metrics.disk_usage,
                    "usage_percent": system_metrics.disk_percent
                },
                "network": {
                    "bytes_sent": system_metrics.network_bytes_sent,
                    "bytes_recv": system_metrics.network_bytes_recv
                },
                "load_average": {
                    "1min": system_metrics.load_average[0],
                    "5min": system_metrics.load_average[1],
                    "15min": system_metrics.load_average[2]
                },
                "processes": {
                    "count": system_metrics.process_count,
                    "threads": system_metrics.thread_count
                }
            }
        }
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/{service_name}")
async def get_service_metrics(service_name: str):
    """Get current metrics for a specific service."""
    try:
        system = get_performance_monitoring_system()
        
        # Collect current service metrics
        service_metrics = await system.collector.collect_service_metrics(service_name)
        
        if not service_metrics:
            raise HTTPException(
                status_code=404, 
                detail=f"Service '{service_name}' not found or not running"
            )
        
        return {
            "status": "success",
            "data": {
                "service_name": service_metrics.service_name,
                "timestamp": service_metrics.timestamp.isoformat(),
                "cpu_percent": service_metrics.cpu_percent,
                "memory": {
                    "usage_bytes": service_metrics.memory_usage,
                    "usage_percent": service_metrics.memory_percent
                },
                "io": {
                    "read_bytes": service_metrics.io_read_bytes,
                    "write_bytes": service_metrics.io_write_bytes
                },
                "threads": service_metrics.thread_count,
                "files": {
                    "open": service_metrics.open_files
                },
                "network": {
                    "connections": service_metrics.network_connections
                },
                "requests": {
                    "count": service_metrics.request_count,
                    "errors": service_metrics.error_count,
                    "response_time": service_metrics.response_time
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting service metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/regressions")
async def detect_regressions(
    hours: int = Query(24, description="Hours to analyze for regressions", ge=1, le=168)
):
    """Detect performance regressions."""
    try:
        system = get_performance_monitoring_system()
        
        regressions = await system.regression_detector.detect_regressions(
            lookback_hours=hours
        )
        
        return {
            "status": "success",
            "data": {
                "regressions": [
                    {
                        "metric_name": r.metric_name,
                        "service_name": r.service_name,
                        "baseline_value": r.baseline_value,
                        "current_value": r.current_value,
                        "change_percent": r.change_percent,
                        "is_regression": r.is_regression,
                        "severity": r.severity.value,
                        "detected_at": r.detected_at.isoformat(),
                        "description": r.description
                    }
                    for r in regressions
                ],
                "count": len(regressions),
                "analysis_period_hours": hours
            }
        }
    except Exception as e:
        logger.error(f"Error detecting regressions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmarks")
async def create_benchmark(request: BenchmarkRequest):
    """Create a performance benchmark."""
    try:
        system = get_performance_monitoring_system()
        
        benchmark = await system.create_benchmark(
            name=request.name,
            duration_minutes=request.duration_minutes,
            services=request.services
        )
        
        return {
            "status": "success",
            "message": f"Benchmark '{request.name}' created successfully",
            "data": benchmark
        }
    except Exception as e:
        logger.error(f"Error creating benchmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/benchmarks")
async def list_benchmarks():
    """List all available benchmarks."""
    try:
        system = get_performance_monitoring_system()
        
        benchmarks = system.benchmark.list_benchmarks()
        
        return {
            "status": "success",
            "data": {
                "benchmarks": benchmarks,
                "count": len(benchmarks)
            }
        }
    except Exception as e:
        logger.error(f"Error listing benchmarks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/benchmarks/{name}")
async def get_benchmark(name: str):
    """Get a specific benchmark."""
    try:
        system = get_performance_monitoring_system()
        
        benchmark = system.benchmark.get_benchmark(name)
        
        if not benchmark:
            raise HTTPException(
                status_code=404, 
                detail=f"Benchmark '{name}' not found"
            )
        
        return {
            "status": "success",
            "data": benchmark
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting benchmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmarks/{name}/compare")
async def compare_to_benchmark(name: str, request: ComparisonRequest):
    """Compare current performance to a benchmark."""
    try:
        system = get_performance_monitoring_system()
        
        comparison = await system.compare_to_benchmark(
            name=request.baseline_name,
            duration_minutes=request.duration_minutes
        )
        
        return {
            "status": "success",
            "data": comparison
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error comparing to benchmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def performance_health():
    """Get performance monitoring system health."""
    try:
        system = get_performance_monitoring_system()
        
        # Check if system is running
        is_running = system.running
        
        # Get basic stats
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=1)
        
        recent_metrics = await system.storage.get_metrics(
            start_time=start_time,
            end_time=end_time,
            limit=100
        )
        
        return {
            "status": "success",
            "data": {
                "monitoring_active": is_running,
                "collection_interval": system.collection_interval,
                "recent_metrics_count": len(recent_metrics),
                "database_path": str(system.db_path),
                "dashboard_active": system.dashboard.running,
                "last_collection": recent_metrics[0].timestamp.isoformat() if recent_metrics else None
            }
        }
    except Exception as e:
        logger.error(f"Error getting performance health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_old_data(
    retention_days: int = Query(30, description="Days of data to retain", ge=1, le=365)
):
    """Clean up old performance data."""
    try:
        system = get_performance_monitoring_system()
        
        deleted_count = await system.cleanup_old_data(retention_days)
        
        return {
            "status": "success",
            "message": f"Cleaned up {deleted_count} old metrics records",
            "data": {
                "deleted_records": deleted_count,
                "retention_days": retention_days
            }
        }
    except Exception as e:
        logger.error(f"Error cleaning up data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/dashboard")
async def export_dashboard_data():
    """Export current dashboard data."""
    try:
        system = get_performance_monitoring_system()
        
        dashboard_data = await system.get_dashboard_data()
        
        return {
            "status": "success",
            "data": dashboard_data,
            "exported_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error exporting dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prometheus")
async def prometheus_metrics():
    """Export metrics in Prometheus format."""
    try:
        system = get_performance_monitoring_system()
        
        # Get recent metrics
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=5)
        
        metrics = await system.storage.get_metrics(
            start_time=start_time,
            end_time=end_time,
            limit=1000
        )
        
        # Convert to Prometheus format
        prometheus_lines = []
        
        for metric in metrics:
            # Create metric name (replace dots with underscores for Prometheus)
            prom_name = metric.name.replace('.', '_').replace('-', '_')
            
            # Add help and type comments
            prometheus_lines.append(f"# HELP {prom_name} {metric.description or metric.name}")
            prometheus_lines.append(f"# TYPE {prom_name} {metric.metric_type.value}")
            
            # Add labels
            labels = []
            labels.append(f'service="{metric.service_name}"')
            
            for key, value in metric.tags.items():
                labels.append(f'{key}="{value}"')
            
            label_str = "{" + ",".join(labels) + "}" if labels else ""
            
            # Add metric line
            timestamp_ms = int(metric.timestamp.timestamp() * 1000)
            prometheus_lines.append(f"{prom_name}{label_str} {metric.value} {timestamp_ms}")
        
        prometheus_text = "\n".join(prometheus_lines)
        
        return Response(
            content=prometheus_text,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        logger.error(f"Error exporting Prometheus metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# Performance Optimization Integration Endpoints

@router.get("/optimization/status")
async def get_optimization_status():
    """Get current performance optimization status."""
    try:
        from ai_karen_engine.server.optimized_startup import (
            get_lifecycle_manager, get_resource_monitor, get_performance_metrics,
            get_lazy_controller, get_task_orchestrator, get_gpu_offloader
        )
        from ai_karen_engine.config.performance_config import get_performance_config
        
        # Get optimization components
        lifecycle_manager = get_lifecycle_manager()
        resource_monitor = get_resource_monitor()
        performance_metrics = get_performance_metrics()
        lazy_controller = get_lazy_controller()
        task_orchestrator = get_task_orchestrator()
        gpu_offloader = get_gpu_offloader()
        
        # Get configuration
        config = get_performance_config()
        
        status = {
            "optimization_enabled": config.enable_performance_optimization if config else False,
            "deployment_mode": config.deployment_mode if config else "unknown",
            "components": {
                "lifecycle_manager": lifecycle_manager is not None,
                "resource_monitor": resource_monitor is not None,
                "performance_metrics": performance_metrics is not None,
                "lazy_controller": lazy_controller is not None,
                "task_orchestrator": task_orchestrator is not None,
                "gpu_offloader": gpu_offloader is not None
            },
            "configuration": config.to_dict() if config else {}
        }
        
        # Add runtime status if components are available
        if resource_monitor:
            try:
                if resource_monitor:
                    try:
                        metrics = resource_monitor.get_current_metrics()
                        status["resource_usage"] = metrics if not asyncio.iscoroutine(metrics) else await metrics
                    except Exception as e:
                        status["resource_usage"] = {"error": str(e)}
                else:
                    status["resource_usage"] = {"error": "Resource monitor not available"}
            except Exception as e:
                status["resource_usage"] = {"error": str(e)}
        
        if performance_metrics:
            try:
                # PerformanceMetrics doesn't have get_summary method, use placeholder
                status["performance_summary"] = {"status": "placeholder", "message": "Performance summary not available"}
            except Exception as e:
                status["performance_summary"] = {"error": str(e)}
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to get optimization status: {e}")
        return {"error": str(e), "optimization_enabled": False}


@router.post("/optimization/audit")
async def run_performance_audit():
    """Run a comprehensive performance audit."""
    try:
        from tools.performance_auditor import PerformanceAuditor
        
        auditor = PerformanceAuditor()
        await auditor.initialize()
        
        # Run both startup and runtime audits
        startup_report = await auditor.audit_startup_performance()
        runtime_report = await auditor.audit_runtime_performance()
        
        # Generate optimization recommendations
        recommendations = await auditor.generate_optimization_recommendations()
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "startup_audit": startup_report,
            "runtime_audit": runtime_report,
            "recommendations": recommendations,
            "summary": {
                "total_services": len(getattr(startup_report, 'services', {})),
                "recommendations_count": len(recommendations),
                "audit_duration": getattr(runtime_report, 'audit_duration', 0)
            }
        }
        
    except Exception as e:
        logger.error(f"Performance audit failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/optimization/trigger")
async def trigger_optimization():
    """Trigger performance optimization actions."""
    try:
        from ai_karen_engine.server.optimized_startup import get_lifecycle_manager
        
        lifecycle_manager = get_lifecycle_manager()
        if not lifecycle_manager:
            raise HTTPException(
                status_code=503,
                detail="Performance optimization not enabled or not available"
            )
        
        # Trigger various optimization actions
        optimization_results = {}
        
        # Service consolidation
        try:
            # Get consolidation opportunities first
            opportunities = lifecycle_manager.identify_consolidation_opportunities()
            if opportunities:
                # Use the first available consolidation group
                first_group = list(opportunities.values())[0]
                consolidation_report = await lifecycle_manager.consolidate_services(group=first_group)
            else:
                consolidation_report = {"message": "No consolidation opportunities available", "status": "none"}
            optimization_results["service_consolidation"] = consolidation_report
        except Exception as e:
            optimization_results["service_consolidation"] = {"error": str(e)}
        
        # Resource optimization
        try:
            # optimize_resource_usage method doesn't exist, use a placeholder
            resource_report = {"message": "Resource optimization not implemented", "status": "placeholder"}
            optimization_results["resource_optimization"] = resource_report
        except Exception as e:
            optimization_results["resource_optimization"] = {"error": str(e)}
        
        # Idle service cleanup
        try:
            # cleanup_idle_services method doesn't exist, use a placeholder
            cleanup_report = {"message": "Idle cleanup not implemented", "status": "placeholder"}
            optimization_results["idle_cleanup"] = cleanup_report
        except Exception as e:
            optimization_results["idle_cleanup"] = {"error": str(e)}
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "optimization_results": optimization_results
        }
        
    except Exception as e:
        logger.error(f"Performance optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimization/services")
async def get_service_status():
    """Get detailed service status and classification."""
    try:
        from ai_karen_engine.server.optimized_startup import get_classified_registry
        
        registry = get_classified_registry()
        if not registry:
            raise HTTPException(
                status_code=503,
                detail="Classified service registry not available"
            )
        
        # Get service information by classification
        services_by_classification = {}
        for classification in ["essential", "optional", "background"]:
            try:
                services = await registry.get_services_by_classification(classification)
                services_by_classification[classification] = {
                    name: {
                        "status": getattr(config, 'status', 'unknown'),
                        "startup_priority": getattr(config, 'startup_priority', 100),
                        "resource_requirements": getattr(config, 'resource_requirements', {}),
                        "dependencies": getattr(config, 'dependencies', []),
                        "idle_timeout": getattr(config, 'idle_timeout', None)
                    }
                    for name, config in services.items()
                }
            except Exception as e:
                services_by_classification[classification] = {"error": str(e)}
        
        # Get overall statistics
        total_services = sum(
            len(services) if isinstance(services, dict) else 0
            for services in services_by_classification.values()
        )
        
        return {
            "services_by_classification": services_by_classification,
            "summary": {
                "total_services": total_services,
                "essential_services": len(services_by_classification.get("essential", {})),
                "optional_services": len(services_by_classification.get("optional", {})),
                "background_services": len(services_by_classification.get("background", {}))
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get service status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimization/config")
async def update_optimization_config(config_updates: Dict[str, Any]):
    """Update performance optimization configuration."""
    try:
        from ai_karen_engine.config.performance_config import get_performance_config_manager
        
        config_manager = get_performance_config_manager()
        
        # Update configuration
        success = await config_manager.update_config(config_updates)
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to update configuration - validation failed"
            )
        
        # Get updated configuration
        updated_config = config_manager.get_config()
        
        return {
            "success": True,
            "message": "Configuration updated successfully",
            "updated_config": updated_config.to_dict() if updated_config else {},
            "applied_updates": config_updates
        }
        
    except Exception as e:
        logger.error(f"Failed to update optimization config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimization/config")
async def get_optimization_config():
    """Get current performance optimization configuration."""
    try:
        from ai_karen_engine.config.performance_config import get_performance_config
        
        config = get_performance_config()
        
        if not config:
            raise HTTPException(
                status_code=503,
                detail="Performance configuration not loaded"
            )
        
        return {
            "configuration": config.to_dict(),
            "deployment_profile": config.get_deployment_profile(),
            "validation_status": config.validate()
        }
        
    except Exception as e:
        logger.error(f"Failed to get optimization config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimization/recommendations")
async def get_optimization_recommendations():
    """Get current optimization recommendations."""
    try:
        from tools.performance_auditor import PerformanceAuditor
        
        auditor = PerformanceAuditor()
        await auditor.initialize()
        
        # Generate recommendations based on current system state
        recommendations = await auditor.generate_optimization_recommendations()
        
        # Categorize recommendations by type
        categorized_recommendations = {
            "high_priority": [],
            "medium_priority": [],
            "low_priority": []
        }
        
        for rec in recommendations:
            priority = getattr(rec, 'priority', 'medium') if hasattr(rec, 'priority') else rec.get("priority", "medium") if isinstance(rec, dict) else "medium"
            if priority in categorized_recommendations:
                categorized_recommendations[priority].append(rec)
            else:
                categorized_recommendations["medium_priority"].append(rec)
        
        return {
            "recommendations": categorized_recommendations,
            "total_recommendations": len(recommendations),
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get optimization recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))
