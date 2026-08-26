# mypy: ignore-errors
"""
FastAPI application factory for Kari Server.
Creates and configures the FastAPI app with all components.

This module remains transitional while application composition moves into
``ai_karen_engine``. Health, readiness, startup lifecycle, and extension
lifecycle authority no longer live in the root ``server`` package.
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .admin_endpoints import register_admin_endpoints
from .config import Settings
from .metrics import (
    ERROR_COUNT,
    PROMETHEUS_ENABLED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    initialize_metrics,
)
from .middleware import configure_middleware
from .performance import load_performance_settings
from .routers import wire_routers
from .security import api_key_header, validate_environment_security
from .validation import initialize_validation_framework
from ai_karen_engine.server.exception_handlers import setup_exception_handlers
from ai_karen_engine.server.startup import create_lifespan

try:
    from prometheus_client import REGISTRY
except ImportError:
    REGISTRY = None

logger = logging.getLogger("kari")


def create_app() -> FastAPI:
    """Create and configure the transitional FastAPI application."""

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
    app_settings = settings

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
    app.state.settings = app_settings

    configure_middleware(app, settings, REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT)
    setup_exception_handlers(app)

    _defer_wiring = os.getenv("KARI_DEFER_ROUTER_WIRING", "false").lower() in (
        "true",
        "yes",
    )
    if _defer_wiring and settings.environment != "production":
        logger.info("Deferring router wiring to background for faster readiness")
    else:
        logger.info("Wiring routers immediately")
        wire_routers(app, settings)
        logger.info("Routers wired successfully")

    register_admin_endpoints(app, settings)

    logger.info("Debug endpoints have been removed for production deployment")
    logger.info("Developer API has been removed for production deployment")
    logger.info("Copilot routes handled through router system")

    try:
        from ai_karen_engine.integrations.copilotkit.routing_actions import (
            ensure_kire_actions_registered,
        )

        ensure_kire_actions_registered()
    except Exception:
        pass

    if _defer_wiring and settings.environment != "production":

        @app.on_event("startup")
        async def _wire_routers_bg() -> None:
            try:
                import asyncio as _asyncio

                await _asyncio.sleep(0.1)
                wire_routers(app, settings)
                logger.info("Routers wired in background")
            except Exception as exc:
                logger.warning("Deferred router wiring failed: %s", exc)

    @app.on_event("shutdown")
    async def _shutdown_database() -> None:
        """Gracefully clean up the settings-bound database configuration."""
        db_config = getattr(app.state, "database_config", None)
        if db_config is None:
            return

        try:
            logger.info("Starting database shutdown process")
            await db_config.cleanup()
            logger.info("Database shutdown completed successfully")
        except Exception as exc:
            logger.error("Error during database shutdown: %s", exc)

    @app.get("/metrics", tags=["monitoring"])
    async def metrics(api_key: str = Depends(api_key_header)):
        """Serve Prometheus metrics with the existing API-key contract."""
        if not PROMETHEUS_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Metrics are not enabled",
            )

        allow_public_metrics = os.getenv(
            "KARI_PUBLIC_METRICS", "false"
        ).lower() in ("true", "yes")

        if not allow_public_metrics and api_key != settings.secret_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.get("/plugins", tags=["plugins"])
    async def list_plugins():
        """List registered and enabled extensions."""
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
            return {
                "enabled": [],
                "available": [],
                "count": 0,
            }

    logger.info("FastAPI application created and configured successfully")
    return app


# Transitional module-level instance retained only while ai_karen_engine.app
# bridges to this package. New process launchers must use the canonical factory.
app = create_app()
