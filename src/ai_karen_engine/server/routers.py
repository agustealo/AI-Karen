"""
Router configuration for Kari FastAPI Server.
Handles all include_router() wiring without changing route definitions.
"""

import os
import importlib
import logging
from typing import Optional, Any, Callable, Type, cast
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.responses import JSONResponse, Response as FastAPIResponse

from .config import Settings


def _ensure_asgi_response(response: FastAPIResponse) -> FastAPIResponse:
    """Ensure downstream responses remain ASGI-callable objects."""
    if callable(response):
        return response

    logger.error(
        "⚠️ Downstream handler returned non-callable response type %s; wrapping in JSONResponse",
        type(response),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


def _http_exception_response(exc: HTTPException) -> FastAPIResponse:
    """Convert HTTPException into a proper ASGI response while preserving headers."""
    content = {"detail": exc.detail} if exc.detail else {}
    response = JSONResponse(status_code=exc.status_code, content=content)
    if exc.headers:
        for header, value in exc.headers.items():
            response.headers[header] = value
    return response


logger = logging.getLogger("kari")

# Original route imports
from ai_karen_engine.api_routes.models.orchestrator import router as ai_router
from ai_karen_engine.api_routes.monitoring.audit import router as audit_router
# DEPRECATED: Complex auth system - replaced with simple auth
# from ai_karen_engine.api_routes.auth import router as auth_router
# from ai_karen_engine.api_routes.auth_session_routes import router as auth_session_router

# NEW: Simple auth system
auth_router: Optional[APIRouter] = None
get_auth_middleware: Optional[Callable[[], Any]] = None
AuthMiddlewareAuthenticationError: Type[Exception] = Exception


class _FallbackAuthenticationError(Exception):
    """Fallback auth error used when auth middleware module is unavailable."""

    def __init__(self, message: str = "Authentication failed", status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


try:
    from ai_karen_engine.api_routes.auth.auth import router as auth_router
    from ai_karen_engine.auth.auth_middleware import (
        AuthenticationError,
        get_auth_middleware,
    )

    AuthMiddlewareAuthenticationError = AuthenticationError

    logger.info("✅ Auth router imported successfully")
except ImportError as e:
    # Fallback - disable auth routes if auth not available
    auth_router = None
    get_auth_middleware = None
    AuthMiddlewareAuthenticationError = _FallbackAuthenticationError
    logger.warning(f"🚫 Auth system not available - auth routes disabled: {e}")
from ai_karen_engine.api_routes.tools.code_execution import (
    router as code_execution_router,
)
from ai_karen_engine.api_routes.chat.conversation import router as conversation_router
from ai_karen_engine.api_routes.artifacts import router as artifacts_router
from ai_karen_engine.api_routes.content.communications import (
    router as communications_center_router,
)

from ai_karen_engine.api_routes.chat.copilot import router as copilot_router
from ai_karen_engine.api_routes.system.events import router as events_router
from ai_karen_engine.api_routes.extensions.extensions import router as extensions_router
from ai_karen_engine.api_routes.plugins.management import (
    router as plugin_management_router,
)
from ai_karen_engine.api_routes.plugins.store import router as plugin_store_router
from ai_karen_engine.api_routes.content.attachments import (
    router as file_attachment_router,
)
from ai_karen_engine.api_routes.memory.memory import router as memory_router
from ai_karen_engine.api_routes.plugins.plugins import router as plugin_router
from ai_karen_engine.api_routes.plugins.plugins import (
    public_router as plugin_public_router,
)
from ai_karen_engine.api_routes.tools.tools import router as tool_router
from ai_karen_engine.api_routes.chat.websocket import router as websocket_router
from ai_karen_engine.api_routes.chat.runtime import router as chat_runtime_router
from ai_karen_engine.api_routes.models.llm import router as llm_router
from ai_karen_engine.api_routes.models.providers import router as provider_router
from ai_karen_engine.api_routes.models.runtime_api import router as runtime_catalog_router
from ai_karen_engine.api_routes.models.providers import (
    public_router as provider_public_router,
)
from ai_karen_engine.api_routes.system.settings import router as settings_router
from ai_karen_engine.api_routes.models.settings import (
    router as model_settings_router,
)
from ai_karen_engine.api_routes.shared.error_response import (
    router as error_response_router,
)
from ai_karen_engine.api_routes.monitoring.analytics import router as analytics_router
from ai_karen_engine.api_routes.agents.integration import (
    router as agent_integration_router,
)
from ai_karen_engine.api_routes.automation.tasks import router as tasks_router
from ai_karen_engine.api_routes.automation.jobs import (
    router as automation_jobs_router,
)
from ai_karen_engine.api_routes.automation.cron import router as automation_cron_router
from ai_karen_engine.api_routes.monitoring.health import router as health_router
from ai_karen_engine.api_routes.models.management import (
    router as model_management_router,
)
from ai_karen_engine.api_routes.automation.scheduler import router as scheduler_router
from ai_karen_engine.api_routes.public.public import router as public_router
from ai_karen_engine.api_routes.models.model_orchestrator import (
    router as model_orchestrator_router,
)
from ai_karen_engine.api_routes.monitoring.validation import (
    router as validation_metrics_router,
)
from ai_karen_engine.api_routes.monitoring.performance import router as performance_routes
from ai_karen_engine.api_routes.models.organization import (
    router as model_organization_router,
)
from ai_karen_engine.api_routes.users.profile import router as user_profile_router
from ai_karen_engine.api_routes.users.persona import router as user_persona_router
from ai_karen_engine.api_routes.users.preferences import (
    router as user_preferences_router,
)
from ai_karen_engine.api_routes.users.data import router as user_data_router
from ai_karen_engine.api_routes.users.users import router as users_router

training_data_router: Optional[APIRouter] = None
try:
    from ai_karen_engine.api_routes.training.data import (
        router as training_data_router,
    )

    TRAINING_DATA_AVAILABLE = True
except ImportError as e:
    training_data_router = None
    TRAINING_DATA_AVAILABLE = False
    logger.warning(f"🚫 Training data routes not available: {e}")
from ai_karen_engine.api_routes.auth.privacy import router as privacy_router
from ai_karen_engine.api_routes.admin.runtime import router as maintenance_router
from ai_karen_engine.extensions.platform.api_routes.ui_materialization_routes import (
    router as ui_materialization_router,
)


# Multi-modal and AI enhancement routes
multimodal_router: Optional[Any] = None
ai_enhancement_router: Optional[Any] = None
MULTIMODAL_AVAILABLE = False

try:
    from ai_karen_engine.api_routes.content.multimodal import router as multimodal_router
    from ai_karen_engine.api_routes.models.ai import router as ai_enhancement_router

    MULTIMODAL_AVAILABLE = True
    logger.info("✅ Multi-modal and AI enhancement routers imported successfully")
except ImportError as e:
    MULTIMODAL_AVAILABLE = False
    logger.warning(f"🚫 Multi-modal routes not available: {e}")

# Extension monitoring system
monitoring_router: Optional[Any] = None
try:
    monitoring_module = importlib.import_module(
        "ai_karen_engine.monitoring.extensions.extension_monitoring_api"
    )
    candidate_router = getattr(monitoring_module, "monitoring_router", None)
    if isinstance(candidate_router, APIRouter):
        monitoring_router = candidate_router
        EXTENSION_MONITORING_AVAILABLE = True
        logger.info("✅ Extension monitoring router imported successfully")
    else:
        EXTENSION_MONITORING_AVAILABLE = False
        logger.warning("🚫 Extension monitoring module found but router is invalid")
except Exception as e:
    # Temporary fallback for in-flight migration paths.
    try:
        monitoring_module = importlib.import_module(
            "ai_karen_engine.server.extension_monitoring_api"
        )
        candidate_router = getattr(monitoring_module, "monitoring_router", None)
        if isinstance(candidate_router, APIRouter):
            monitoring_router = candidate_router
            EXTENSION_MONITORING_AVAILABLE = True
            logger.info(
                "✅ Extension monitoring router imported via legacy fallback path"
            )
        else:
            monitoring_router = None
            EXTENSION_MONITORING_AVAILABLE = False
            logger.warning(
                "🚫 Extension monitoring module found via fallback but router is invalid"
            )
    except Exception as legacy_error:
        monitoring_router = None
        EXTENSION_MONITORING_AVAILABLE = False
        logger.warning(
            "🚫 Extension monitoring not available: canonical import error=%s; fallback import error=%s",
            e,
            legacy_error,
        )


def wire_routers(app: FastAPI, settings: Settings) -> None:
    """Wire all routers to the FastAPI app with simplified auth system"""

    logger.info("🔧 Starting router wiring...")

    # NEW: Simple authentication system
    logger.info(f"🔍 Auth router status: {auth_router is not None}")
    if auth_router:
        try:
            app.include_router(auth_router, prefix="/api", tags=["authentication"])
            logger.info("🔐 Auth router loaded successfully")
        except Exception as e:
            logger.error(f"Failed to include auth router: {e}", exc_info=True)
    else:
        logger.warning("🚫 Auth router not available")

    # Environment check for auth mode
    effective_env = (
        os.getenv("ENVIRONMENT") or os.getenv("KARI_ENV") or settings.environment
    ).lower()
    auth_mode = os.getenv("AUTH_MODE", "production").lower()

    logger.info(f"🔐 Using auth system - AUTH_MODE={auth_mode}")

    # Add auth middleware globally (if available)
    try:
        if get_auth_middleware is None:
            raise ImportError("auth middleware factory not available")

        auth_middleware = get_auth_middleware()

        # Use FastAPI middleware for global auth
        @app.middleware("http")
        async def auth_middleware_handler(request, call_next):
            # Check for development bypass mode first
            from ai_karen_engine.core.security.auth_config import auth_config

            auth_bypass = auth_config.should_bypass_auth()

            skip_auth_header = request.headers.get("X-Skip-Auth")
            dev_mode_header = request.headers.get("X-Development-Mode")

            if auth_bypass or (skip_auth_header == "dev" and dev_mode_header == "true"):
                # Development mode - set mock user context directly
                mock_user_id = request.headers.get("X-Mock-User-ID", "dev-user")
                request.state.user = {
                    "user_id": mock_user_id,
                    "email": "admin@karen.ai",
                    "user_type": "developer",
                    "roles": ["admin", "user"],
                    "permissions": [
                        "extension:*",
                        "chat:write",
                        "memory:read",
                        "memory:write",
                        "admin:*",
                    ],
                    "token_id": "dev-token-id",
                    "tenant_id": "default",
                }
                logger.info(
                    f"🔓 Middleware bypass: auth_bypass={auth_bypass}, mock_user_id={mock_user_id}, path={request.url.path}"
                )
            else:
                # Primary skip auth for public endpoints
                path = str(request.url.path)
                if (
                    auth_middleware.is_public_endpoint(path)
                    or path.startswith("/metrics")
                    or path.startswith("/health")
                    or path.startswith("/api/health")
                    or path == "/api/auth/validate-session"
                ):
                    response = await call_next(request)
                    return _ensure_asgi_response(response)

                # For protected endpoints, authenticate and add user to request state
                try:
                    authenticate_request = getattr(
                        auth_middleware, "authenticate_request", None
                    )
                    if callable(authenticate_request):
                        user_data = await authenticate_request(request)
                    else:
                        user_data = await auth_middleware.get_current_user(request)
                    request.state.user = user_data
                except HTTPException as exc:
                    logger.warning(
                        "🚫 Authentication failed for %s %s: %s",
                        request.method,
                        request.url.path,
                        exc.detail,
                    )
                    return _http_exception_response(exc)
                except AuthMiddlewareAuthenticationError as exc:
                    # If it's an extension endpoint, we might want to allow guest access
                    if request.url.path.startswith("/api/extensions"):
                        request.state.user = {
                            "user_id": "guest",
                            "email": "guest@karen.ai",
                            "user_type": "user",
                            "permissions": ["extension:read"],
                            "tenant_id": "default",
                            "authenticated": False
                        }
                    else:
                        # Handle specific authentication errors
                        status_code = int(getattr(exc, "status_code", 401))
                        message = str(getattr(exc, "message", str(exc)))
                        logger.warning(
                            "🚫 Authentication error for %s %s: %s",
                            request.method,
                            request.url.path,
                            message,
                        )
                        return _http_exception_response(
                            HTTPException(status_code=status_code, detail=message)
                        )
                except Exception as exc:
                    # If it's an extension endpoint, we might want to allow guest access
                    if request.url.path.startswith("/api/extensions"):
                        request.state.user = {
                            "user_id": "guest",
                            "email": "guest@karen.ai",
                            "user_type": "user",
                            "permissions": ["extension:read"],
                            "tenant_id": "default",
                            "authenticated": False
                        }
                    else:
                        # Log unexpected authentication errors with full context
                        logger.exception(
                            "⚠️ Unexpected error during authentication for %s %s: %s",
                            request.method,
                            request.url.path,
                            str(exc),
                        )
                        # Return 401 instead of 500 if possible to avoid terminal UI errors
                        return _http_exception_response(
                            HTTPException(
                                status_code=401,
                                detail=f"Authentication service error: {str(exc)}",
                            )
                        )

            response = await call_next(request)
            return _ensure_asgi_response(response)

        logger.info("🔐 Auth middleware loaded successfully")
    except ImportError:
        logger.warning("🚫 Auth middleware not available")

    # Core API routers
    app.include_router(events_router, prefix="/api/events", tags=["events"])
    app.include_router(websocket_router, prefix="/api/ws", tags=["websocket"])
    app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
    app.include_router(
        communications_center_router,
        prefix="/api/communications-center",
        tags=["communications-center"],
    )
    if TRAINING_DATA_AVAILABLE and isinstance(training_data_router, APIRouter):
        app.include_router(training_data_router, tags=["training-data"])
    else:
        logger.warning("🚫 Training data router not available")
    if privacy_router is not None:
        app.include_router(
            cast(APIRouter, privacy_router), prefix="/api", tags=["privacy"]
        )
    else:
        logger.warning("🚫 Privacy router not available")
    try:
        app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
        logger.info("🤖 AI router loaded successfully")
    except Exception as e:
        logger.error(f"Failed to include AI router: {e}", exc_info=True)
    app.include_router(agent_integration_router, tags=["agents"])
    app.include_router(tasks_router, tags=["tasks"])
    app.include_router(automation_jobs_router, prefix="/api", tags=["automation-jobs"])
    app.include_router(automation_cron_router, prefix="/api", tags=["automation-cron"])
    app.include_router(memory_router, prefix="/api/memory", tags=["memory"])
    app.include_router(user_persona_router, prefix="/api/personas", tags=["personas"])

    # Align copilot routes under /api to match frontend expectations
    app.include_router(copilot_router, prefix="/api/copilot", tags=["copilot"])
    try:
        app.include_router(
            conversation_router, prefix="/api/conversations", tags=["conversations"]
        )
        logger.info("💬 Conversation router loaded successfully")
    except Exception as e:
        logger.error(f"Failed to include conversation router: {e}", exc_info=True)
    try:
        app.include_router(artifacts_router, prefix="/api/artifacts", tags=["artifacts"])
        logger.info("📦 Artifacts router loaded successfully")
    except Exception as e:
        logger.error(f"Failed to include artifacts router: {e}", exc_info=True)
    app.include_router(plugin_router, prefix="/api/plugins", tags=["plugins"])
    app.include_router(plugin_store_router, prefix="/api", tags=["plugin-store"])
    app.include_router(plugin_public_router, tags=["plugins-public"])
    app.include_router(tool_router, prefix="/api/tools", tags=["tools"])
    # Audit router enabled
    app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
    # Extensions router
    app.include_router(extensions_router, prefix="/api/extensions", tags=["extensions"])
    app.include_router(
        plugin_management_router, prefix="/api/plugins", tags=["plugin-management"]
    )
    app.include_router(ui_materialization_router, tags=["ui-materialization"])
    app.include_router(file_attachment_router, prefix="/api/files", tags=["files"])
    app.include_router(code_execution_router, prefix="/api/code", tags=["code"])
    app.include_router(chat_runtime_router, prefix="/api/chat", tags=["chat-runtime"])
    app.include_router(llm_router, prefix="/api/llm", tags=["llm"])

    # Mock provider routes removed for production
    logger.info("🚫 Mock provider routes disabled for production")

    # Provider and model routers
    app.include_router(provider_router, prefix="/api/providers", tags=["providers"])
    app.include_router(runtime_catalog_router, prefix="/api", tags=["runtime"])
    app.include_router(
        provider_public_router,
        prefix="/api/public/providers",
        tags=["public-providers"],
    )
    app.include_router(user_profile_router, prefix="/api/profiles", tags=["profiles"])
    app.include_router(users_router, prefix="/api", tags=["users"])
    app.include_router(error_response_router, prefix="/api", tags=["error-response"])
    # Health router already defines a "/health" prefix, so mount it at the API root
    # to expose endpoints like "/api/health" and "/api/health/degraded-mode".
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(model_management_router, tags=["model-management"])
    app.include_router(scheduler_router, tags=["scheduler"])
    app.include_router(public_router, tags=["public"])
    app.include_router(model_orchestrator_router, tags=["model-orchestrator"])
    app.include_router(validation_metrics_router, tags=["validation-metrics"])
    app.include_router(performance_routes, tags=["performance"])
    app.include_router(model_organization_router, tags=["model-organization"])
    app.include_router(user_preferences_router)
    app.include_router(user_data_router, prefix="/api", tags=["user-data"])
    app.include_router(settings_router)
    app.include_router(model_settings_router, prefix="/api", tags=["model-settings"])
    app.include_router(maintenance_router, prefix="/api", tags=["maintenance"])

    # Multi-modal and AI enhancement routes
    if MULTIMODAL_AVAILABLE:
        if isinstance(multimodal_router, APIRouter):
            app.include_router(multimodal_router, tags=["multimodal"])
            logger.info("🎨 Multi-modal router loaded successfully")
        if isinstance(ai_enhancement_router, APIRouter):
            app.include_router(ai_enhancement_router, tags=["ai-enhancement"])
            logger.info("🧠 AI enhancement router loaded successfully")
    else:
        logger.warning("🚫 Multi-modal and AI enhancement routes not available")

    # Extension monitoring system
    if EXTENSION_MONITORING_AVAILABLE and isinstance(monitoring_router, APIRouter):
        app.include_router(monitoring_router, tags=["extension-monitoring"])
        logger.info("📊 Extension monitoring router loaded successfully")
    else:
        logger.warning("🚫 Extension monitoring router not available")
