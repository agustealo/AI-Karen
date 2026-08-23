# mypy: ignore-errors
"""
FastAPI application factory for Kari Server.
Creates and configures the FastAPI app with all components.
"""

import os
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# Import all modular components
from ai_karen_engine.config import Settings
from ai_karen_engine.server.logging_setup import configure_logging
from ai_karen_engine.server.security import (
    pwd_context,
    api_key_header,
    oauth2_scheme,
    get_ssl_context,
    require_extension_read,
    require_background_tasks,
    require_extension_write,
    require_extension_admin,
)
from ai_karen_engine.server.metrics import (
    initialize_metrics,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    ERROR_COUNT,
    PROMETHEUS_ENABLED,
)

try:
    from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST
except ImportError:
    REGISTRY = None

from ai_karen_engine.server.validation import initialize_validation_framework
from ai_karen_engine.server.middleware import configure_middleware
from ai_karen_engine.server.performance import load_performance_settings
from ai_karen_engine.server.routers import wire_routers
from ai_karen_engine.server.startup import (
    create_lifespan_with_extensions,
    register_startup_tasks,
    register_shutdown_tasks,
)
from ai_karen_engine.services.database.database_config import get_database_config
from ai_karen_engine.server.admin_endpoints import register_admin_endpoints
from ai_karen_engine.server.health_endpoints import register_health_endpoints
from ai_karen_engine.server.security import validate_environment_security
from ai_karen_engine.server.exception_handlers import setup_exception_handlers

logger = logging.getLogger("kari")

# Extension system integration
try:
    from ai_karen_engine.extensions.platform.core.host.factory import (
        initialize_extensions_for_production as initialize_extensions,
    )

    EXTENSIONS_AVAILABLE = True
except ImportError as canonical_error:
    try:
        # Temporary fallback for migration compatibility.
        from ai_karen_engine.extensions.platform.core.host.factory import (  # type: ignore
            initialize_extensions_for_production as initialize_extensions,
        )

        EXTENSIONS_AVAILABLE = True
        logger.info("✅ Extension system imported via legacy fallback path")
    except ImportError as legacy_error:
        EXTENSIONS_AVAILABLE = False
        logger.warning(
            "Extension system not available (canonical=%s, fallback=%s)",
            canonical_error,
            legacy_error,
        )

initialize_extension_system = initialize_extensions

# Initialize logging EARLY to ensure all subsequent imports use configured loggers
configure_logging()

# Global variables from original main.py
ENABLED_PLUGINS = []
PLUGIN_MAP = {}


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""

    # Run security policy validation before continuing
    # This protects against missing secrets before the server starts.
    validation = validate_environment_security()
    if validation["overall_status"] != "secure":
        invalid_secrets = [
            key
            for key, result in validation["secrets_validation"].items()
            if not result["valid"]
        ]
        logger.critical(
            "Environment security validation failed: %s. Invalid secrets: %s",
            validation["overall_status"],
            invalid_secrets or "None (check policy constraints)",
        )
        raise RuntimeError(
            "Environment security validation failed; check server logs for details."
        )

    # Load configuration (environment loading is handled in config module)
    settings = Settings()
    environment = settings.environment.lower()
    # Load performance configuration
    load_performance_settings(settings)

    # Initialize validation framework
    initialize_validation_framework(settings)

    # Setup metrics
    initialize_metrics()

    # Create lifespan manager with database configuration and extension initialization
    lifespan = create_lifespan_with_extensions(settings)

    # Initialize database configuration
    db_config = get_database_config(settings)

    # Create FastAPI app
    app = FastAPI(
        title="Kari AI Assistant API",
        description="Advanced AI assistant with multi-modal capabilities",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Configure middleware
    configure_middleware(app, settings, REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT)

    # Setup custom exception handlers
    setup_exception_handlers(app)

    # Optionally defer router wiring to speed up initial readiness in dev
    # Default to immediate wiring so critical routes (e.g. auth) are available
    # before the first request without requiring special environment flags.
    _defer_wiring = os.getenv("KARI_DEFER_ROUTER_WIRING", "false").lower() in (
        "true",
        "yes",
    )
    if _defer_wiring and settings.environment != "production":
        logger.info("⚡ Deferring router wiring to background for faster readiness")
    else:
        # Wire all routers immediately (production/default)
        logger.info("🔧 Wiring routers immediately...")
        wire_routers(app, settings)
        logger.info("✅ Routers wired successfully")

    # Register startup tasks
    register_startup_tasks(app)

    # Register shutdown tasks for extension service recovery
    register_shutdown_tasks(app)

    # Register endpoint groups
    register_admin_endpoints(app, settings)
    register_health_endpoints(app)

    # Debug endpoints removed for production readiness
    logger.info("Debug endpoints have been removed for production deployment")

    # Developer API removed for production readiness
    logger.info("Developer API has been removed for production deployment")

    # Initialize extension system (only if database is available)
    if EXTENSIONS_AVAILABLE:
        app.add_event_handler("startup", initialize_extension_system)
    else:
        logger.info("Extension system disabled")

    # Add comprehensive health check endpoint
    @app.get("/health", tags=["system"])
    async def health_check():
        """Comprehensive health check with fallback status including extension system"""
        try:
            from datetime import datetime, timezone
            from pathlib import Path

            # Check service registry status
            service_status = {}
            try:
                from ai_karen_engine.core.services.service_registry import ServiceRegistry

                registry = ServiceRegistry()
                report = registry.get_initialization_report()
                service_status = {
                    "total_services": report["summary"]["total_services"],
                    "ready_services": report["summary"]["ready_services"],
                    "degraded_services": report["summary"]["degraded_services"],
                    "error_services": report["summary"]["error_services"],
                }
            except Exception:
                service_status = {"status": "unknown"}

            # Check connection health with enhanced database information
            connection_status = {}
            try:
                from ai_karen_engine.database.client import get_database_client
                from ai_karen_engine.core.memory.redis_connection_manager import (
                    get_redis_manager,
                )

                db_client = get_database_client()
                redis_manager = get_redis_manager()

                # Get detailed database status
                db_health = await db_config.get_database_health()

                connection_status = {
                    "database": {
                        "status": "degraded" if db_client.is_degraded() else "healthy",
                        "pool_info": db_health.get("pool_info", {}),
                        "configuration": db_health.get("configuration", {}),
                        "connection_failures": db_health.get("connection_failures", 0),
                    },
                    "redis": "degraded" if redis_manager.is_degraded() else "healthy",
                }
            except Exception as e:
                connection_status = {
                    "database": {"status": "unknown", "error": str(e)},
                    "redis": "unknown",
                }

            # Check extension system health
            extension_status = {}
            try:
                from ai_karen_engine.extensions.health_monitor import (
                    get_extension_health_monitor,
                )

                extension_monitor = get_extension_health_monitor()
                if extension_monitor:
                    ext_health = await extension_monitor.get_extension_health_for_api()
                    extension_status = {
                        "status": ext_health["status"],
                        "total_extensions": ext_health["extensions"]["total"],
                        "healthy_extensions": ext_health["extensions"]["healthy"],
                        "degraded_extensions": ext_health["extensions"]["degraded"],
                        "unhealthy_extensions": ext_health["extensions"]["unhealthy"],
                        "authentication_healthy": ext_health["supporting_services"][
                            "authentication"
                        ]["healthy"],
                        "database_healthy": ext_health["supporting_services"][
                            "database"
                        ]["healthy"],
                        "background_tasks_healthy": ext_health["supporting_services"][
                            "background_tasks"
                        ]["healthy"],
                    }
                else:
                    extension_status = {"status": "unknown", "monitor_available": False}
            except Exception as e:
                extension_status = {"status": "error", "error": str(e)}

            # Check model availability
            model_status = {}
            try:
                models_dir = Path("models")
                gguf_models = list(models_dir.rglob("*.gguf"))
                bin_models = list(models_dir.rglob("*.bin"))

                model_status = {
                    "local_models": len(gguf_models) + len(bin_models),
                    "fallback_available": len(gguf_models) > 0,
                }
            except Exception:
                model_status = {"local_models": 0, "fallback_available": False}

            # Check model orchestrator health
            model_orchestrator_status = {}
            try:
                from ai_karen_engine.health.model_orchestrator_health import (
                    get_model_orchestrator_health,
                )

                health_checker = get_model_orchestrator_health()
                orchestrator_health = await health_checker.check_health()
                model_orchestrator_status = {
                    "status": orchestrator_health.get("status", "unknown"),
                    "registry_healthy": orchestrator_health.get(
                        "registry_healthy", False
                    ),
                    "storage_healthy": orchestrator_health.get(
                        "storage_healthy", False
                    ),
                    "plugin_loaded": "model_orchestrator" in ENABLED_PLUGINS,
                    "last_check": orchestrator_health.get("timestamp"),
                }
            except Exception as e:
                model_orchestrator_status = {
                    "status": "error",
                    "error": str(e),
                    "plugin_loaded": "model_orchestrator" in ENABLED_PLUGINS,
                }

            # Determine overall status including extension system
            overall_status = "healthy"
            if (
                connection_status.get("database") == "degraded"
                or connection_status.get("redis") == "degraded"
            ):
                overall_status = "degraded"
            if service_status.get("error_services", 0) > 0:
                overall_status = "degraded"
            if extension_status.get("status") == "degraded":
                overall_status = "degraded"
            if extension_status.get("status") == "unhealthy":
                overall_status = "unhealthy"

            return {
                "status": overall_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": settings.environment,
                "version": "1.0.0",
                "services": service_status,
                "connections": connection_status,
                "extension_system": extension_status,
                "models": model_status,
                "model_orchestrator": model_orchestrator_status,
                "plugins": len(ENABLED_PLUGINS),
                "fallback_systems": {
                    "analytics": "active",
                    "error_responses": "active",
                    "provider_chains": "active",
                    "connection_health": "active",
                    "extension_graceful_degradation": "active",
                },
            }

        except Exception as e:
            from datetime import datetime, timezone

            return {
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": settings.environment,
                "version": "1.0.0",
                "error": str(e),
                "fallback_mode": True,
            }

    # Background task to wire routers after startup, if deferred
    if _defer_wiring and settings.environment != "production":

        @app.on_event("startup")
        async def _wire_routers_bg() -> None:
            try:
                import asyncio as _asyncio

                # Small delay to allow server to bind
                await _asyncio.sleep(0.1)
                wire_routers(app, settings)
                logger.info("✅ Routers wired in background")
            except Exception as _e:
                logger.warning(f"Deferred router wiring failed: {_e}")

    # Add metrics endpoint
    @app.get("/metrics", tags=["monitoring"])
    async def metrics(api_key: str = Depends(api_key_header)):
        """Prometheus metrics endpoint requiring X-API-KEY header with extension metrics"""
        if not PROMETHEUS_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Metrics are not enabled",
            )
        if api_key != settings.secret_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        # Ensure extension metrics are up-to-date before serving
        try:
            from ai_karen_engine.extensions.health_monitor import (
                get_extension_health_monitor,
            )

            extension_monitor = get_extension_health_monitor()
            if extension_monitor:
                # Force a health check to update metrics
                health = await extension_monitor.check_extension_system_health()
                extension_monitor.update_extension_metrics(health)
        except Exception as e:
            logger.warning(f"Failed to update extension metrics before serving: {e}")

        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )

    # Add plugins endpoint
    @app.get("/plugins", tags=["plugins"])
    async def list_plugins():
        """List all plugins with detailed status"""
        return {
            "enabled": sorted(ENABLED_PLUGINS),
            "available": sorted(PLUGIN_MAP.keys()),
            "count": len(PLUGIN_MAP),
        }

    # Add database health endpoint
    @app.get("/api/health/database", tags=["system"])
    async def database_health():
        """Database health check endpoint with detailed connection information"""
        try:
            health_info = await db_config.get_database_health()
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": health_info,
            }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": {"status": "error", "healthy": False, "error": str(e)},
            }

    # Add database connection test endpoint
    @app.get("/api/health/database/test", tags=["system"])
    async def test_database_connection():
        """Test database connection with timeout"""
        try:
            start_time = datetime.now(timezone.utc)
            success = await db_config.test_database_connection()
            end_time = datetime.now(timezone.utc)

            response_time = (end_time - start_time).total_seconds() * 1000

            return {
                "timestamp": start_time.isoformat(),
                "connection_test": {
                    "success": success,
                    "response_time_ms": response_time,
                    "timeout_configured": settings.db_connection_timeout,
                },
            }
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connection_test": {
                    "success": False,
                    "error": str(e),
                    "timeout_configured": settings.db_connection_timeout,
                },
            }

    # Add degraded mode status endpoint
    @app.get("/api/health/degraded-mode", tags=["system"])
    async def degraded_mode_status():
        """Compatibility proxy that forwards to the canonical health router."""

        try:
            from ai_karen_engine.api_routes.monitoring.health import (
                degraded_mode_status_compat,
            )

            payload = await degraded_mode_status_compat()

            # Enhance payload with extension system information
            try:
                from ai_karen_engine.extensions.health_monitor import (
                    get_extension_health_monitor,
                )

                extension_monitor = get_extension_health_monitor()
                if extension_monitor:
                    ext_health = await extension_monitor.get_extension_health_for_api()
                    payload["extension_system"] = {
                        "status": ext_health["status"],
                        "total_extensions": ext_health["extensions"]["total"],
                        "healthy_extensions": ext_health["extensions"]["healthy"],
                        "degraded_extensions": ext_health["extensions"]["degraded"],
                        "unhealthy_extensions": ext_health["extensions"]["unhealthy"],
                        "authentication_healthy": ext_health["supporting_services"][
                            "authentication"
                        ]["healthy"],
                        "database_healthy": ext_health["supporting_services"][
                            "database"
                        ]["healthy"],
                        "background_tasks_healthy": ext_health["supporting_services"][
                            "background_tasks"
                        ]["healthy"],
                        "degraded_extension_names": [
                            name
                            for name, details in ext_health["extensions"][
                                "details"
                            ].items()
                            if details["status"] in ["degraded", "unhealthy"]
                        ],
                        "uptime_seconds": ext_health["uptime_seconds"],
                    }

                    # Update degraded mode status based on extension health
                    if ext_health["status"] in ["degraded", "unhealthy"]:
                        payload["degraded_mode"] = True
                        payload["is_active"] = True
                        if "degraded_components" not in payload:
                            payload["degraded_components"] = []
                        if ext_health["status"] == "unhealthy":
                            payload["degraded_components"].append("extension_system")
                        elif ext_health["status"] == "degraded":
                            payload["degraded_components"].append(
                                "extension_system_partial"
                            )
                else:
                    payload["extension_system"] = {
                        "status": "unknown",
                        "monitor_available": False,
                    }
            except Exception as e:
                logger.warning(
                    f"Failed to enhance degraded mode with extension info: {e}"
                )
                payload["extension_system"] = {"status": "error", "error": str(e)}

            return payload
        except Exception as exc:
            logger.warning("Degraded mode proxy fallback due to error: %s", exc)

            # Get extension system status for degraded mode reporting
            extension_degraded_info = {}
            try:
                from ai_karen_engine.extensions.health_monitor import (
                    get_extension_health_monitor,
                )

                extension_monitor = get_extension_health_monitor()
                if extension_monitor:
                    ext_health = await extension_monitor.get_extension_health_for_api()
                    extension_degraded_info = {
                        "extension_system_status": ext_health["status"],
                        "total_extensions": ext_health["extensions"]["total"],
                        "healthy_extensions": ext_health["extensions"]["healthy"],
                        "degraded_extensions": ext_health["extensions"]["degraded"],
                        "unhealthy_extensions": ext_health["extensions"]["unhealthy"],
                        "extension_authentication_healthy": ext_health[
                            "supporting_services"
                        ]["authentication"]["healthy"],
                        "extension_database_healthy": ext_health["supporting_services"][
                            "database"
                        ]["healthy"],
                        "extension_background_tasks_healthy": ext_health[
                            "supporting_services"
                        ]["background_tasks"]["healthy"],
                        "degraded_extension_names": [
                            name
                            for name, details in ext_health["extensions"][
                                "details"
                            ].items()
                            if details["status"] in ["degraded", "unhealthy"]
                        ],
                    }
                else:
                    extension_degraded_info = {
                        "extension_system_status": "unknown",
                        "extension_monitor_available": False,
                    }
            except Exception as e:
                logger.warning(f"Failed to get extension status for degraded mode: {e}")
                extension_degraded_info = {
                    "extension_system_status": "error",
                    "extension_error": str(e),
                }

            return {
                "degraded_mode": True,
                "is_active": True,
                "ai_status": "degraded",
                "reason": "health_check_failed",
                "failed_providers": [],
                "degraded_components": ["health_router"],
                "core_helpers_available": {
                    "fallback_responses": True,
                    "local_fallback_ready": False,
                },
                "fallback_systems_active": True,
                "extension_system": extension_degraded_info,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }

    logger.info("FastAPI application created and configured successfully")
    return app


# Create the FastAPI app instance for uvicorn
app = create_app()
