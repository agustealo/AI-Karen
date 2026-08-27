"""Canonical FastAPI router and authentication composition for AI KAREN.

This module is the single application-level router registry. Route modules own
request schemas and thin ingress handlers; this registry owns only mounting and
the global authenticated-request boundary. Admin endpoints are intentionally
excluded because ``ai_karen_engine.server.admin_endpoints`` is their single
registration owner.
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ai_karen_engine.api_routes.artifacts import router as artifacts_router
from ai_karen_engine.api_routes.auth.auth import router as auth_router
from ai_karen_engine.api_routes.auth.privacy import router as privacy_router
from ai_karen_engine.api_routes.agents.integration import router as agent_integration_router
from ai_karen_engine.api_routes.automation.cron import router as automation_cron_router
from ai_karen_engine.api_routes.automation.jobs import router as automation_jobs_router
from ai_karen_engine.api_routes.automation.scheduler import router as scheduler_router
from ai_karen_engine.api_routes.automation.tasks import router as tasks_router
from ai_karen_engine.api_routes.chat.conversation import router as conversation_router
from ai_karen_engine.api_routes.chat.copilot import router as copilot_router
from ai_karen_engine.api_routes.chat.runtime import router as chat_runtime_router
from ai_karen_engine.api_routes.chat.websocket import router as websocket_router
from ai_karen_engine.api_routes.content.attachments import router as file_attachment_router
from ai_karen_engine.api_routes.content.communications import router as communications_center_router
from ai_karen_engine.api_routes.extensions.extensions import router as extensions_router
from ai_karen_engine.api_routes.memory.memory import router as memory_router
from ai_karen_engine.api_routes.models.llm import router as llm_router
from ai_karen_engine.api_routes.models.management import router as model_management_router
from ai_karen_engine.api_routes.models.model_orchestrator import router as model_orchestrator_router
from ai_karen_engine.api_routes.models.orchestrator import router as ai_router
from ai_karen_engine.api_routes.models.organization import router as model_organization_router
from ai_karen_engine.api_routes.models.providers import public_router as provider_public_router
from ai_karen_engine.api_routes.models.providers import router as provider_router
from ai_karen_engine.api_routes.models.runtime_api import router as runtime_catalog_router
from ai_karen_engine.api_routes.models.settings import router as model_settings_router
from ai_karen_engine.api_routes.monitoring.analytics import router as analytics_router
from ai_karen_engine.api_routes.monitoring.audit import router as audit_router
from ai_karen_engine.api_routes.monitoring.health import router as health_router
from ai_karen_engine.api_routes.monitoring.performance import router as performance_router
from ai_karen_engine.api_routes.monitoring.validation import router as validation_metrics_router
from ai_karen_engine.api_routes.plugins.management import router as plugin_management_router
from ai_karen_engine.api_routes.plugins.plugins import public_router as plugin_public_router
from ai_karen_engine.api_routes.plugins.plugins import router as plugin_router
from ai_karen_engine.api_routes.plugins.store import router as plugin_store_router
from ai_karen_engine.api_routes.public.public import router as public_router
from ai_karen_engine.api_routes.shared.error_response import router as error_response_router
from ai_karen_engine.api_routes.system.events import router as events_router
from ai_karen_engine.api_routes.system.settings import router as settings_router
from ai_karen_engine.api_routes.tools.code_execution import router as code_execution_router
from ai_karen_engine.api_routes.tools.tools import router as tool_router
from ai_karen_engine.api_routes.users.data import router as user_data_router
from ai_karen_engine.api_routes.users.persona import router as user_persona_router
from ai_karen_engine.api_routes.users.profile import router as user_profile_router
from ai_karen_engine.api_routes.users.users import router as users_router
from ai_karen_engine.auth.auth_middleware import AuthenticationError, get_auth_middleware
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.extensions.platform.api_routes.ui_materialization_routes import (
    router as ui_materialization_router,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouterSpec:
    """Declarative router registration contract."""

    router: APIRouter
    prefix: str = ""
    tags: tuple[str, ...] = ()


CORE_ROUTERS: tuple[RouterSpec, ...] = (
    RouterSpec(auth_router, "/api", ("authentication",)),
    RouterSpec(events_router, "/api/events", ("events",)),
    RouterSpec(websocket_router, "/api/ws", ("websocket",)),
    RouterSpec(analytics_router, "/api/analytics", ("analytics",)),
    RouterSpec(
        communications_center_router,
        "/api/communications-center",
        ("communications-center",),
    ),
    RouterSpec(privacy_router, "/api", ("privacy",)),
    RouterSpec(ai_router, "/api/ai", ("ai",)),
    RouterSpec(agent_integration_router, tags=("agents",)),
    RouterSpec(tasks_router, tags=("tasks",)),
    RouterSpec(automation_jobs_router, "/api", ("automation-jobs",)),
    RouterSpec(automation_cron_router, "/api", ("automation-cron",)),
    RouterSpec(memory_router, "/api/memory", ("memory",)),
    RouterSpec(user_persona_router, "/api/personas", ("personas",)),
    RouterSpec(copilot_router, "/api/copilot", ("copilot",)),
    RouterSpec(conversation_router, "/api/conversations", ("conversations",)),
    RouterSpec(artifacts_router, "/api/artifacts", ("artifacts",)),
    RouterSpec(plugin_router, "/api/plugins", ("plugins",)),
    RouterSpec(plugin_store_router, "/api", ("plugin-store",)),
    RouterSpec(plugin_public_router, tags=("plugins-public",)),
    RouterSpec(tool_router, "/api/tools", ("tools",)),
    RouterSpec(audit_router, "/api/audit", ("audit",)),
    RouterSpec(extensions_router, "/api/extensions", ("extensions",)),
    RouterSpec(plugin_management_router, "/api/plugins", ("plugin-management",)),
    RouterSpec(ui_materialization_router, tags=("ui-materialization",)),
    RouterSpec(file_attachment_router, "/api/files", ("files",)),
    RouterSpec(code_execution_router, "/api/code", ("code",)),
    # runtime.py defines /chat and /stream itself, so the app-level prefix is /api.
    RouterSpec(chat_runtime_router, "/api", ("chat-runtime",)),
    RouterSpec(llm_router, "/api/llm", ("llm",)),
    RouterSpec(provider_router, "/api/providers", ("providers",)),
    RouterSpec(runtime_catalog_router, "/api", ("runtime",)),
    RouterSpec(provider_public_router, "/api/public/providers", ("public-providers",)),
    RouterSpec(user_profile_router, "/api/profiles", ("profiles",)),
    RouterSpec(users_router, "/api", ("users",)),
    RouterSpec(error_response_router, "/api", ("error-response",)),
    RouterSpec(health_router, "/api", ("health",)),
    RouterSpec(model_management_router, tags=("model-management",)),
    RouterSpec(scheduler_router, tags=("scheduler",)),
    RouterSpec(public_router, tags=("public",)),
    RouterSpec(model_orchestrator_router, tags=("model-orchestrator",)),
    RouterSpec(validation_metrics_router, tags=("validation-metrics",)),
    RouterSpec(performance_router, tags=("performance",)),
    RouterSpec(model_organization_router, tags=("model-organization",)),
    RouterSpec(user_data_router, "/api", ("user-data",)),
    RouterSpec(settings_router),
    RouterSpec(model_settings_router, "/api", ("model-settings",)),
)


OPTIONAL_ROUTERS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "ai_karen_engine.api_routes.training.data",
        "router",
        "",
        ("training-data",),
    ),
    (
        "ai_karen_engine.api_routes.content.multimodal",
        "router",
        "",
        ("multimodal",),
    ),
    (
        "ai_karen_engine.api_routes.models.ai",
        "router",
        "",
        ("ai-enhancement",),
    ),
    (
        "ai_karen_engine.monitoring.extensions.extension_monitoring_api",
        "monitoring_router",
        "",
        ("extension-monitoring",),
    ),
)


def _http_error(exc: HTTPException) -> JSONResponse:
    """Translate authentication boundary failures without leaking internals."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=dict(exc.headers or {}),
    )


def _configured_development_identity() -> dict[str, Any]:
    """Resolve explicit local bypass identity without synthesizing tenant scope."""
    user_id = os.getenv("KARI_DEV_USER_ID", "").strip()
    tenant_id = os.getenv("KARI_DEV_TENANT_ID", "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication bypass requires explicit KARI_DEV_USER_ID and "
                "KARI_DEV_TENANT_ID configuration"
            ),
        )

    roles = [
        role.strip()
        for role in os.getenv("KARI_DEV_ROLES", "user").split(",")
        if role.strip()
    ]
    permissions = [
        permission.strip()
        for permission in os.getenv("KARI_DEV_PERMISSIONS", "chat:write").split(",")
        if permission.strip()
    ]
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "permissions": permissions,
        "authenticated": True,
        "auth_source": "configured_development_bypass",
    }


def configure_authentication_middleware(app: FastAPI) -> None:
    """Install the fail-closed global authenticated-request boundary."""
    auth_middleware = get_auth_middleware()

    @app.middleware("http")
    async def canonical_authentication(request: Request, call_next):
        path = request.url.path

        if auth_config.should_bypass_auth():
            try:
                request.state.user = _configured_development_identity()
            except HTTPException as exc:
                return _http_error(exc)
            return await call_next(request)

        if (
            auth_middleware.is_public_endpoint(path)
            or path.startswith("/metrics")
            or path.startswith("/health")
            or path.startswith("/api/health")
            or path == "/api/auth/validate-session"
        ):
            return await call_next(request)

        try:
            authenticate_request = getattr(
                auth_middleware,
                "authenticate_request",
                None,
            )
            if callable(authenticate_request):
                user_data = await authenticate_request(request)
            else:
                user_data = await auth_middleware.get_current_user(request)
            request.state.user = user_data
        except HTTPException as exc:
            logger.warning(
                "Authentication rejected request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status_code": exc.status_code,
                },
            )
            return _http_error(exc)
        except AuthenticationError as exc:
            status_code = int(getattr(exc, "status_code", 401))
            message = str(getattr(exc, "message", str(exc)))
            logger.warning(
                "Authentication rejected request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status_code": status_code,
                },
            )
            return _http_error(
                HTTPException(status_code=status_code, detail=message)
            )
        except Exception:
            logger.exception(
                "Authentication service unavailable",
                extra={"method": request.method, "path": path},
            )
            return _http_error(
                HTTPException(
                    status_code=503,
                    detail="Authentication service unavailable",
                )
            )

        return await call_next(request)


def _include_specs(app: FastAPI, specs: Iterable[RouterSpec]) -> None:
    for spec in specs:
        app.include_router(
            spec.router,
            prefix=spec.prefix,
            tags=list(spec.tags) if spec.tags else None,
        )


def _include_optional_routers(app: FastAPI) -> None:
    for module_name, attribute, prefix, tags in OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            candidate = getattr(module, attribute, None)
        except ImportError:
            logger.info("Optional router unavailable: %s", module_name)
            continue

        if not isinstance(candidate, APIRouter):
            logger.warning(
                "Optional router has invalid contract: %s.%s",
                module_name,
                attribute,
            )
            continue
        app.include_router(candidate, prefix=prefix, tags=list(tags))


def wire_routers(app: FastAPI, settings: Any) -> None:
    """Mount canonical routers exactly once and install authentication."""
    del settings
    configure_authentication_middleware(app)
    _include_specs(app, CORE_ROUTERS)
    _include_optional_routers(app)
    logger.info("Canonical API routers registered")


__all__ = [
    "CORE_ROUTERS",
    "RouterSpec",
    "configure_authentication_middleware",
    "wire_routers",
]
