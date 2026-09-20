"""Canonical FastAPI application entrypoint for AI KAREN.

All process launchers, containers, and deployment adapters must import the
application factory from this module. Canonical configuration, middleware,
security, performance, router registration, admin registration, lifecycle, and
exception handling all live under ``ai_karen_engine.server``.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from ai_karen_engine.api_routes.models.unavailable_capabilities import (
    router as unavailable_model_capabilities_router,
)
from ai_karen_engine.api_routes.monitoring.metrics import router as metrics_router
from ai_karen_engine.api_routes.monitoring.probes import router as probe_router
from ai_karen_engine.platform.observability.http_metrics import (
    ERROR_COUNT,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from ai_karen_engine.server.admin_endpoints import register_admin_endpoints
from ai_karen_engine.server.application_runtime import create_application_lifespan
from ai_karen_engine.server.config import Settings
from ai_karen_engine.server.exception_handlers import setup_exception_handlers
from ai_karen_engine.server.middleware import configure_middleware
from ai_karen_engine.server.performance import load_performance_settings
from ai_karen_engine.server.routers import wire_routers
from ai_karen_engine.server.security import validate_environment_security

logger = logging.getLogger("kari")

_PROBES_REGISTERED_STATE_KEY = "_canonical_probe_routes_registered"
_METRICS_REGISTERED_STATE_KEY = "_canonical_metrics_routes_registered"
_UNAVAILABLE_MODEL_CAPABILITIES_REGISTERED_STATE_KEY = (
    "_unavailable_model_capabilities_registered"
)


def _validate_environment() -> None:
    validation = validate_environment_security()
    if validation["overall_status"] == "secure":
        return

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


def _register_canonical_routes(app: FastAPI) -> None:
    if not getattr(
        app.state,
        _UNAVAILABLE_MODEL_CAPABILITIES_REGISTERED_STATE_KEY,
        False,
    ):
        app.include_router(unavailable_model_capabilities_router)
        setattr(
            app.state,
            _UNAVAILABLE_MODEL_CAPABILITIES_REGISTERED_STATE_KEY,
            True,
        )

    if not getattr(app.state, _PROBES_REGISTERED_STATE_KEY, False):
        app.include_router(probe_router)
        setattr(app.state, _PROBES_REGISTERED_STATE_KEY, True)

    if not getattr(app.state, _METRICS_REGISTERED_STATE_KEY, False):
        app.include_router(metrics_router)
        setattr(app.state, _METRICS_REGISTERED_STATE_KEY, True)


def create_app() -> FastAPI:
    """Construct the canonical AI KAREN ASGI application directly."""
    _validate_environment()

    settings = Settings()
    load_performance_settings(settings)

    app = FastAPI(
        title="Kari AI Assistant API",
        description="Advanced AI assistant with multi-modal capabilities",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=create_application_lifespan(settings),
    )
    app.state.settings = settings

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

    register_admin_endpoints(app, settings)

    try:
        from ai_karen_engine.integrations.copilotkit.routing_actions import (
            ensure_kire_actions_registered,
        )

        ensure_kire_actions_registered()
    except Exception:
        logger.debug("CopilotKit routing actions unavailable", exc_info=True)

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

    _register_canonical_routes(app)

    logger.info("Canonical FastAPI application created successfully")
    return app


__all__ = ["create_app"]
