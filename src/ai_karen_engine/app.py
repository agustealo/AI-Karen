# mypy: ignore-errors
"""Canonical FastAPI application factory for AI KAREN.

This module is the single public ASGI composition authority. Deployment
adapters, local launchers, Docker, and tests must target
``ai_karen_engine.app:create_app``.

The remaining ``server`` imports are transitional composition helpers. They are
migrated by ownership in later SERVER-CONVERGE slices; they must not become new
runtime authorities here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from server.admin_endpoints import register_admin_endpoints
from server.config import Settings
from server.database_config import get_database_config
from server.health_endpoints import register_health_endpoints
from server.metrics import (
    ERROR_COUNT,
    PROMETHEUS_ENABLED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    initialize_metrics,
)
from server.middleware import configure_middleware
from server.performance import load_performance_settings
from server.routers import wire_routers
from server.security import api_key_header, validate_environment_security
from server.startup import create_lifespan, register_shutdown_tasks, register_startup_tasks
from server.validation import initialize_validation_framework

from ai_karen_engine.server.exception_handlers import setup_exception_handlers

try:
    from prometheus_client import REGISTRY
except ImportError:
    REGISTRY = None

logger = logging.getLogger("kari")

try:
    from ai_karen_engine.extensions.platform.core.host.factory import (
        initialize_extensions_for_production as initialize_extensions,
    )

    EXTENSIONS_AVAILABLE = True
except ImportError:
    EXTENSIONS_AVAILABLE = False
    logger.warning("Extension system not available")


def _model_orchestrator_plugin_loaded() -> bool:
    try:
        from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
        from ai_karen_engine.extensions.registry import ExtensionRegistry

        registry = ExtensionRegistry()
        registration = registry.get("model_orchestrator")
        return registration is not None and registration.state == ExtensionLifecycleState.ENABLED
    except Exception:
        return False


def _count_registered_extensions() -> int:
    try:
        from ai_karen_engine.extensions.registry import ExtensionRegistry

        registry = ExtensionRegistry()
        return len(registry.list_registered())
    except Exception:
        return 0


def create_app() -> FastAPI:
    """Create and configure the canonical AI KAREN FastAPI application."""

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

    settings = Settings()
    db_config = get_database_config(settings)
    load_performance_settings(settings)
    initialize_validation_framework(settings)
    initialize_metrics()

    lifespan = create_lifespan(settings)
    app = FastAPI(
        title="Kari AI Assistant API",
        description="Advanced AI assistant with multi-modal capabilities",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database_config = db_config

    configure_middleware(app, settings, REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT)
    setup_exception_handlers(app)

    defer_wiring = os.getenv("KARI_DEFER_ROUTER_WIRING", "false").lower() in (
        "true",
        "yes",
    )
    if defer_wiring and settings.environment != "production":
        logger.info("Deferring router wiring to background for faster readiness")
    else:
        logger.info("Wiring routers immediately")
        wire_routers(app, settings)
        logger.info("Routers wired successfully")

    register_startup_tasks(app)
    register_shutdown_tasks(app)
    register_admin_endpoints(app, settings)
    register_health_endpoints(app)

    if EXTENSIONS_AVAILABLE:

        async def initialize_extension_system() -> None:
            if not getattr(app.state, "database_available", False):
                logger.info(
                    "Skipping extension system initialization (database not available)"
                )
                return

            try:
                from ai_karen_engine.extensions.platform.core.host.factory import (
                    ExtensionServiceConfig,
                    initialize_extensions_for_production,
                )

                ext_config = ExtensionServiceConfig(
                    extension_root="src/ai_karen_engine/extensions/plugins",
                )
                extension_manager = initialize_extensions_for_production(ext_config)
                app.state.extension_system = extension_manager

                try:
                    from server.extension_health_monitor import (
                        initialize_extension_health_monitor,
                    )

                    if extension_manager:
                        await initialize_extension_health_monitor(extension_manager)
                        logger.info("Extension health monitoring initialized")
                    else:
                        logger.warning("Extension manager unavailable")
                except Exception as monitor_error:
                    logger.warning(
                        "Extension health monitoring failed: %s", monitor_error
                    )
            except Exception as exc:
                logger.warning("Extension system initialization error: %s", exc)

        app.router.on_startup.append(initialize_extension_system)
    else:
        logger.info("Extension system disabled")

    async def shutdown_extension_health_monitoring() -> None:
        try:
            from server.extension_health_monitor import shutdown_extension_health_monitor

            await shutdown_extension_health_monitor()
            logger.info("Extension health monitoring shutdown completed")
        except Exception as exc:
            logger.warning("Extension health monitoring shutdown error: %s", exc)

    app.router.on_shutdown.append(shutdown_extension_health_monitoring)

    try:
        from ai_karen_engine.integrations.copilotkit.routing_actions import (
            ensure_kire_actions_registered,
        )

        ensure_kire_actions_registered()
    except Exception:
        pass

    @app.get("/health", tags=["system"])
    async def health_check():
        try:
            from pathlib import Path

            service_status = {}
            try:
                from ai_karen_engine.core.service_registry import ServiceRegistry

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

            connection_status = {}
            try:
                from ai_karen_engine.services.database.database_connection_manager import (
                    get_database_manager,
                )
                from ai_karen_engine.services.redis_connection_manager import (
                    get_redis_manager,
                )

                db_manager = get_database_manager()
                redis_manager = get_redis_manager()
                db_health = await db_config.get_database_health()
                connection_status = {
                    "database": {
                        "status": "degraded" if db_manager.is_degraded() else "healthy",
                        "pool_info": db_health.get("pool_info", {}),
                        "configuration": db_health.get("configuration", {}),
                        "connection_failures": db_health.get("connection_failures", 0),
                    },
                    "redis": "degraded" if redis_manager.is_degraded() else "healthy",
                }
            except Exception as exc:
                connection_status = {
                    "database": {"status": "unknown", "error": str(exc)},
                    "redis": "unknown",
                }

            extension_status = {}
            try:
                from server.extension_health_monitor import get_extension_health_monitor

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
                        "database_healthy": ext_health["supporting_services"]["database"][
                            "healthy"
                        ],
                        "background_tasks_healthy": ext_health["supporting_services"][
                            "background_tasks"
                        ]["healthy"],
                    }
                else:
                    extension_status = {"status": "unknown", "monitor_available": False}
            except Exception as exc:
                extension_status = {"status": "error", "error": str(exc)}

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

            try:
                from ai_karen_engine.health.model_orchestrator_health import (
                    get_model_orchestrator_health,
                )

                health_checker = get_model_orchestrator_health()
                orchestrator_health = await health_checker.check_health()
                model_orchestrator_status = {
                    "status": orchestrator_health.get("status", "unknown"),
                    "registry_healthy": orchestrator_health.get("registry_healthy", False),
                    "storage_healthy": orchestrator_health.get("storage_healthy", False),
                    "plugin_loaded": _model_orchestrator_plugin_loaded(),
                    "last_check": orchestrator_health.get("timestamp"),
                }
            except Exception as exc:
                model_orchestrator_status = {
                    "status": "error",
                    "error": str(exc),
                    "plugin_loaded": _model_orchestrator_plugin_loaded(),
                }

            overall_status = "healthy"
            database_state = connection_status.get("database", {})
            if isinstance(database_state, dict) and database_state.get("status") == "degraded":
                overall_status = "degraded"
            if connection_status.get("redis") == "degraded":
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
                "plugins": _count_registered_extensions(),
            }
        except Exception as exc:
            return {
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": settings.environment,
                "version": "1.0.0",
                "error": str(exc),
                "fallback_mode": True,
            }

    if defer_wiring and settings.environment != "production":

        @app.on_event("startup")
        async def _wire_routers_bg() -> None:
            try:
                import asyncio

                await asyncio.sleep(0.1)
                wire_routers(app, settings)
                logger.info("Routers wired in background")
            except Exception as exc:
                logger.warning("Deferred router wiring failed: %s", exc)

    @app.on_event("shutdown")
    async def _shutdown_database() -> None:
        try:
            logger.info("Starting database shutdown process")
            await db_config.cleanup()
            logger.info("Database shutdown completed successfully")
        except Exception as exc:
            logger.error("Error during database shutdown: %s", exc)

    @app.get("/metrics", tags=["monitoring"])
    async def metrics(api_key: str = Depends(api_key_header)):
        if not PROMETHEUS_ENABLED:
            raise HTTPException(status_code=501, detail="Metrics are not enabled")

        allow_public_metrics = os.getenv("KARI_PUBLIC_METRICS", "false").lower() in (
            "true",
            "yes",
        )
        if not allow_public_metrics and api_key != settings.secret_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        try:
            from server.extension_health_monitor import get_extension_health_monitor

            extension_monitor = get_extension_health_monitor()
            if extension_monitor:
                health = await extension_monitor.check_extension_system_health()
                extension_monitor.update_extension_metrics(health)
        except Exception as exc:
            logger.warning("Failed to update extension metrics before serving: %s", exc)

        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/plugins", tags=["plugins"])
    async def list_plugins():
        try:
            from ai_karen_engine.extensions.registry import ExtensionRegistry

            registry = ExtensionRegistry()
            registered = registry.list_registered()
            enabled = registry.list_enabled()
            return {
                "enabled": sorted(r.manifest.id for r in enabled),
                "available": sorted(r.manifest.id for r in registered),
                "count": len(registered),
            }
        except Exception:
            return {"enabled": [], "available": [], "count": 0}

    @app.get("/api/health/database", tags=["system"])
    async def database_health():
        try:
            health_info = await db_config.get_database_health()
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": health_info,
            }
        except Exception as exc:
            logger.error("Database health check failed: %s", exc)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": {"status": "error", "healthy": False, "error": str(exc)},
            }

    @app.get("/api/health/database/test", tags=["system"])
    async def test_database_connection():
        try:
            start_time = datetime.now(timezone.utc)
            success = await db_config.test_database_connection()
            response_time = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds() * 1000
            return {
                "timestamp": start_time.isoformat(),
                "connection_test": {
                    "success": success,
                    "response_time_ms": response_time,
                    "timeout_configured": settings.db_connection_timeout,
                },
            }
        except Exception as exc:
            logger.error("Database connection test failed: %s", exc)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connection_test": {
                    "success": False,
                    "error": str(exc),
                    "timeout_configured": settings.db_connection_timeout,
                },
            }

    @app.get("/api/health/degraded-mode", tags=["system"])
    async def degraded_mode_status():
        try:
            from ai_karen_engine.api_routes.monitoring.health import (
                degraded_mode_status_compat,
            )

            payload = await degraded_mode_status_compat()
            return payload
        except Exception as exc:
            logger.warning("Degraded mode proxy fallback due to error: %s", exc)
            return {
                "degraded_mode": True,
                "is_active": True,
                "ai_status": "degraded",
                "reason": "health_check_failed",
                "failed_providers": [],
                "degraded_components": ["health_router"],
                "fallback_systems_active": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }

    logger.info("FastAPI application created and configured successfully")
    return app
