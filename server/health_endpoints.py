# mypy: ignore-errors
"""
Health and status endpoints for Kari FastAPI Server.
Handles health checks, ping, and status endpoints with comprehensive monitoring.

Requirements: 5.1, 5.4
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException

logger = logging.getLogger("kari")


async def _check_database_health() -> Dict[str, Any]:
    """Check database connectivity and health."""
    try:
        from ai_karen_engine.services.database_connection_manager import (
            get_database_manager,
        )

        db_manager = get_database_manager()
        start_time = time.time()

        # Perform a simple query to test connectivity
        is_connected = await db_manager.test_connection()
        response_time = (time.time() - start_time) * 1000

        return {
            "status": "healthy"
            if is_connected and not db_manager.is_degraded()
            else "degraded",
            "connected": is_connected,
            "degraded": db_manager.is_degraded(),
            "response_time_ms": response_time,
            "pool_size": getattr(db_manager, "pool_size", 0),
            "active_connections": getattr(db_manager, "active_connections", 0),
        }
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(e),
            "response_time_ms": 0,
        }


async def _check_redis_health() -> Dict[str, Any]:
    """Check Redis connectivity and health."""
    try:
        from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager

        redis_manager = get_redis_manager()
        start_time = time.time()

        # Test Redis connectivity
        is_connected = await redis_manager.test_connection()
        response_time = (time.time() - start_time) * 1000

        return {
            "status": "healthy"
            if is_connected and not redis_manager.is_degraded()
            else "degraded",
            "connected": is_connected,
            "degraded": redis_manager.is_degraded(),
            "response_time_ms": response_time,
        }
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(e),
            "response_time_ms": 0,
        }


async def _check_ai_providers_health() -> Dict[str, Any]:
    """Check AI providers and model availability."""
    try:
        from ai_karen_engine.services.provider_registry import (
            get_provider_registry_service,
        )

        provider_service = get_provider_registry_service()
        system_status = provider_service.get_system_status()

        total_providers = system_status.get("total_providers", 0)
        available_providers = system_status.get("available_providers", 0)
        failed_providers = system_status.get("failed_providers", [])

        # Check local model availability
        local_models = 0
        try:
            from pathlib import Path

            models_dir = Path("models")
            if models_dir.exists():
                local_models = len(list(models_dir.glob("**/*.gguf")))
        except Exception:
            pass

        status = (
            "healthy" if available_providers > 0 or local_models > 0 else "degraded"
        )

        return {
            "status": status,
            "total_providers": total_providers,
            "available_providers": available_providers,
            "failed_providers": failed_providers,
            "local_models": local_models,
            "provider_details": system_status.get("provider_details", {}),
        }
    except Exception as e:
        logger.warning(f"AI providers health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "total_providers": 0,
            "available_providers": 0,
            "local_models": 0,
        }


async def _check_system_resources() -> Dict[str, Any]:
    """Check system resource usage."""
    try:
        import psutil

        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # Disk usage
        disk = psutil.disk_usage("/")
        disk_percent = disk.percent

        # Determine overall status
        status = "healthy"
        if cpu_percent > 90 or memory_percent > 90 or disk_percent > 90:
            status = "degraded"
        if cpu_percent > 95 or memory_percent > 95 or disk_percent > 95:
            status = "unhealthy"

        return {
            "status": status,
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_percent": disk_percent,
            "memory_available_gb": memory.available / (1024**3),
            "disk_free_gb": disk.free / (1024**3),
        }
    except Exception as e:
        logger.warning(f"System resources health check failed: {e}")
        return {
            "status": "unknown",
            "error": str(e),
        }


async def _check_extension_system_health() -> Dict[str, Any]:
    """Check extension system health with integration to existing monitoring patterns."""
    try:
        from .extension_health_monitor import get_extension_health_monitor

        extension_monitor = get_extension_health_monitor()
        if not extension_monitor:
            return {
                "status": "unknown",
                "error": "Extension health monitor not initialized",
                "total_extensions": 0,
                "healthy_extensions": 0,
                "degraded_extensions": 0,
                "unhealthy_extensions": 0,
            }

        # Get comprehensive extension health
        health_data = await extension_monitor.get_extension_health_for_api()

        return {
            "status": health_data["status"],
            "total_extensions": health_data["extensions"]["total"],
            "healthy_extensions": health_data["extensions"]["healthy"],
            "degraded_extensions": health_data["extensions"]["degraded"],
            "unhealthy_extensions": health_data["extensions"]["unhealthy"],
            "uptime_seconds": health_data["uptime_seconds"],
            "supporting_services": health_data["supporting_services"],
            "extension_details": health_data["extensions"]["details"],
        }

    except Exception as e:
        logger.warning(f"Extension system health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "total_extensions": 0,
            "healthy_extensions": 0,
            "degraded_extensions": 0,
            "unhealthy_extensions": 0,
        }


def register_health_endpoints(app: FastAPI) -> None:
    """Register all health and status endpoints"""

    @app.get("/api/ping", tags=["system"])
    async def api_ping():
        """Simple ping endpoint for basic connectivity testing."""
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.get("/ping", tags=["system"])
    async def root_ping():
        """Root ping endpoint for basic connectivity testing."""
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.get("/health", tags=["system"])
    async def root_health():
        """Basic health check endpoint."""
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.get("/api/health", tags=["system"])
    async def comprehensive_health():
        """Comprehensive health check with detailed service status including extensions."""
        start_time = time.time()
        timestamp = datetime.now(timezone.utc)

        # Check all services including extensions
        database_health = await _check_database_health()
        redis_health = await _check_redis_health()
        ai_providers_health = await _check_ai_providers_health()
        system_resources = await _check_system_resources()
        extension_system_health = await _check_extension_system_health()

        # Determine overall status
        service_statuses = [
            database_health["status"],
            redis_health["status"],
            ai_providers_health["status"],
            system_resources["status"],
            extension_system_health["status"],
        ]

        if any(status == "unhealthy" for status in service_statuses):
            overall_status = "unhealthy"
        elif any(status == "degraded" for status in service_statuses):
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        response_time = (time.time() - start_time) * 1000

        return {
            "status": overall_status,
            "timestamp": timestamp.isoformat(),
            "response_time_ms": response_time,
            "services": {
                "database": database_health,
                "redis": redis_health,
                "ai_providers": ai_providers_health,
                "system_resources": system_resources,
                "extension_system": extension_system_health,
            },
            "summary": {
                "healthy_services": sum(
                    1 for status in service_statuses if status == "healthy"
                ),
                "degraded_services": sum(
                    1 for status in service_statuses if status == "degraded"
                ),
                "unhealthy_services": sum(
                    1 for status in service_statuses if status == "unhealthy"
                ),
                "total_services": len(service_statuses),
            },
        }

    @app.get("/api/health/database", tags=["system"])
    async def database_health():
        """Database-specific health check."""
        health = await _check_database_health()
        if health["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        return health

    @app.get("/api/health/redis", tags=["system"])
    async def redis_health():
        """Redis-specific health check."""
        health = await _check_redis_health()
        if health["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        return health

    @app.get("/api/health/ai-providers", tags=["system"])
    async def ai_providers_health():
        """AI providers-specific health check."""
        health = await _check_ai_providers_health()
        if health["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        return health

    @app.get("/api/health/system", tags=["system"])
    async def system_health():
        """System resources health check."""
        health = await _check_system_resources()
        if health["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        return health

    @app.get("/api/health/extensions", tags=["system"])
    async def extension_system_health():
        """Extension system health check."""
        health = await _check_extension_system_health()
        if health["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        return health

    @app.get("/api/health/extensions/{extension_name}", tags=["system"])
    async def specific_extension_health(extension_name: str):
        """Health check for a specific extension."""
        try:
            from .extension_health_monitor import get_extension_health_monitor

            extension_monitor = get_extension_health_monitor()
            if not extension_monitor:
                raise HTTPException(
                    status_code=503, detail="Extension health monitor not available"
                )

            health = await extension_monitor.check_specific_extension_health(
                extension_name
            )

            if health["status"] == "not_found":
                raise HTTPException(
                    status_code=404, detail=f"Extension {extension_name} not found"
                )
            elif health["status"] in ["unhealthy", "error"]:
                raise HTTPException(status_code=503, detail=health)

            return health

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking health for extension {extension_name}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to check extension health: {str(e)}"
            )

    @app.get("/api/health/extensions/recovery/status", tags=["system"])
    async def extension_recovery_status():
        """Get extension service recovery system status."""
        try:
            from .extension_service_recovery import (
                get_extension_service_recovery_manager,
            )

            recovery_manager = get_extension_service_recovery_manager()
            if not recovery_manager:
                raise HTTPException(
                    status_code=503,
                    detail="Extension service recovery manager not available",
                )

            status = recovery_manager.get_recovery_status()
            return status

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting extension recovery status: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get recovery status: {str(e)}"
            )

    @app.get("/api/health/extensions/recovery/history", tags=["system"])
    async def extension_recovery_history(hours: int = 24):
        """Get extension service recovery history."""
        try:
            from .extension_service_recovery import (
                get_extension_service_recovery_manager,
            )

            recovery_manager = get_extension_service_recovery_manager()
            if not recovery_manager:
                raise HTTPException(
                    status_code=503,
                    detail="Extension service recovery manager not available",
                )

            history = recovery_manager.get_recovery_history(hours)
            return {
                "history": history,
                "hours": hours,
                "total_recoveries": len(history),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting extension recovery history: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get recovery history: {str(e)}"
            )

    @app.post("/api/health/extensions/recovery/force/{service_name}", tags=["system"])
    async def force_extension_recovery(service_name: str, strategy: str = None):
        """Force a recovery attempt for a specific extension service."""
        try:
            from .extension_service_recovery import (
                get_extension_service_recovery_manager,
                RecoveryStrategy,
            )

            recovery_manager = get_extension_service_recovery_manager()
            if not recovery_manager:
                raise HTTPException(
                    status_code=503,
                    detail="Extension service recovery manager not available",
                )

            # Parse strategy if provided
            recovery_strategy = None
            if strategy:
                try:
                    recovery_strategy = RecoveryStrategy(strategy)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid recovery strategy: {strategy}. Valid strategies: {[s.value for s in RecoveryStrategy]}",
                    )

            success = await recovery_manager.force_recovery(
                service_name, recovery_strategy
            )

            if success:
                return {
                    "message": f"Recovery queued for {service_name}",
                    "service": service_name,
                    "strategy": recovery_strategy.value
                    if recovery_strategy
                    else "auto",
                    "status": "queued",
                }
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Service {service_name} not found or cannot be recovered",
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error forcing recovery for {service_name}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to force recovery: {str(e)}"
            )

    @app.get("/api/status", tags=["system"])
    async def api_status():
        """Detailed system status endpoint."""
        timestamp = datetime.now(timezone.utc)

        # Get basic system info
        try:
            import platform
            import sys

            system_info = {
                "platform": platform.platform(),
                "python_version": sys.version,
                "architecture": platform.architecture()[0],
                "processor": platform.processor(),
            }
        except Exception:
            system_info = {"error": "Could not retrieve system info"}

        return {
            "status": "ok",
            "timestamp": timestamp.isoformat(),
            "uptime_seconds": time.time()
            - getattr(app.state, "start_time", time.time()),
            "system_info": system_info,
            "version": getattr(app.state, "version", "unknown"),
        }
