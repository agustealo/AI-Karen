import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import StreamingResponse

from ai_karen_engine.middleware.error_counter import error_counter_middleware
from ai_karen_engine.middleware.rate_limit import rate_limit_middleware
from ai_karen_engine.middleware.intelligent_error_handler import (
    IntelligentErrorHandlerMiddleware,
)
from ai_karen_engine.core.logging.middleware import RuntimeLoggingMiddleware
from ai_karen_engine.core.logging import get_logger, bind_log_context

# REMOVED: RBAC and session persistence middleware - replaced with simple auth
from ai_karen_engine.server.http_validator import HTTPRequestValidator, ValidationConfig

logger = get_logger(__name__)


def configure_middleware(
    app: FastAPI,
    settings: Any,
    request_count,
    request_latency,
    error_count,
) -> None:
    """Configure all FastAPI middleware."""
    
    if settings.https_redirect:
        app.add_middleware(HTTPSRedirectMiddleware)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="starlette_session",
        same_site="lax",
        https_only=settings.https_redirect,
    )

    # Resolve CORS origins from multiple sources for compatibility
    # Priority: explicit env CORS_ORIGINS -> env KARI_CORS_ORIGINS -> settings -> defaults
    import os as _os

    _origins_source = (
        _os.getenv("CORS_ORIGINS")
        or _os.getenv("KARI_CORS_ORIGINS")
        or getattr(settings, "kari_cors_origins", "")
        or ""
    )
    origins = [o.strip() for o in _origins_source.split(",") if o.strip()]

    # Add default development origins if none specified
    env_name = (getattr(settings, "environment", "") or "").lower()
    if not origins and env_name in ("development", "dev", "local", ""):
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8020",
            "http://127.0.0.1:8020",
            "http://localhost:8001",  # Frontend development server
            "http://127.0.0.1:8001",  # Frontend development server
            "http://localhost:8010",
            "http://127.0.0.1:8010",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "https://localhost:3000",
            "https://127.0.0.1:3000",
            "https://localhost:8020",
            "https://127.0.0.1:8020",
            "https://localhost:8001",  # Frontend development server
            "https://127.0.0.1:8001",  # Frontend development server
            "https://localhost:8010",
            "https://127.0.0.1:8010",
            "https://localhost:8080",
            "https://127.0.0.1:8080",
        ]

    # Safety: de-duplicate while preserving order
    _seen = set()
    origins = [o for o in origins if not (o in _seen or _seen.add(o))]
    # Optional regex-based allowance, useful for dev ports/hosts
    cors_regex = _os.getenv("CORS_ALLOW_ORIGIN_REGEX")
    allow_dev_origins = _os.getenv("ALLOW_DEV_ORIGINS", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    # Default to permissive localhost regex in non-production or when explicitly enabled
    if not cors_regex and (
        allow_dev_origins or env_name in ("development", "dev", "local", "")
    ):
        cors_regex = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=cors_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time", "X-Process-Time"],
        max_age=600,
    )

    # Use more conservative GZip settings to prevent MemoryError on high-load/low-memory systems.
    # Higher minimum_size (5KB) avoids compression overhead for small JSON responses.
    # Lower compresslevel (5 instead of default 9) significantly reduces memory allocation 
    # for compression objects while still providing good compression ratios.
    app.add_middleware(GZipMiddleware, minimum_size=5000, compresslevel=5)

    # Ensure streaming responses are not served with a stale Content-Length.
    # Some upstream handlers and error paths may set Content-Length on a body
    # that is later streamed/altered (e.g., by compression), which can trigger
    # "Response content longer than Content-Length" in Uvicorn.
    @app.middleware("http")
    async def strip_content_length_for_streams(request: Request, call_next):
        try:
            response = await call_next(request)

        except RuntimeError as exc:
            if request.url.path.startswith(
                "/api/copilot/assist"
            ) and "No response returned" in str(exc):
                from ai_karen_engine.server.exception_handlers import (
                    _build_copilot_degraded_response,
                )
                from fastapi.responses import JSONResponse

                logger.warning(
                    "Returning degraded Copilot response after middleware chain dropped the response"
                )
                return JSONResponse(
                    status_code=200,
                    content=_build_copilot_degraded_response(request, exc),
                )
            raise
        try:
            # Remove Content-Length for true streaming responses
            if isinstance(response, StreamingResponse):
                response.headers.pop("content-length", None)
                return response

            # Also remove when content is encoded (size may change after gzip/br)
            enc = response.headers.get("content-encoding", "").lower()
            if enc in ("gzip", "br", "deflate"):
                response.headers.pop("content-length", None)

        except Exception:
            # Do not interfere with the response in case of header mutations failing
            pass
        return response

    @app.middleware("http")
    async def fix_internal_redirects(request: Request, call_next):
        """
        Intercepts absolute redirects containing internal Docker hostnames
        and rewrites them to be relative or use the correct forwarded host.
        """
        try:
            response = await call_next(request)

        except RuntimeError as exc:
            if request.url.path.startswith(
                "/api/copilot/assist"
            ) and "No response returned" in str(exc):
                from ai_karen_engine.server.exception_handlers import (
                    _build_copilot_degraded_response,
                )
                from fastapi.responses import JSONResponse

                logger.warning(
                    "Returning degraded Copilot response from redirect middleware after dropped inner response"
                )
                return JSONResponse(
                    status_code=200,
                    content=_build_copilot_degraded_response(request, exc),
                )
            raise

        # We only care about redirects (301, 302, 307, 308)
        if response.status_code in (301, 302, 307, 308):
            location = response.headers.get("location")
            if location:
                # Internal hostnames commonly used in Docker/K8s
                internal_hosts = [
                    "api:8000",
                    "api-copilot:8000",
                    "localhost:8000",
                    "host.docker.internal:8000",
                ]
                for host in internal_hosts:
                    if f"http://{host}" in location or f"https://{host}" in location:
                        # Extract the forwarded host if provided by a proxy (like Next.js)
                        # Otherwise fall back to the Host header
                        external_host = request.headers.get(
                            "x-forwarded-host"
                        ) or request.headers.get("host")
                        if external_host:
                            # Reconstruct the URL using the correct host and protocol
                            from urllib.parse import urlparse, urlunparse

                            parsed = urlparse(location)
                            # Preserve the original protocol (http/https) from the redirect unless we are explicitly TLS terminated
                            scheme = (
                                request.headers.get("x-forwarded-proto")
                                or parsed.scheme
                            )
                            new_location = urlunparse(
                                (
                                    scheme,
                                    external_host,
                                    parsed.path,
                                    parsed.params,
                                    parsed.query,
                                    parsed.fragment,
                                )
                            )

                            logger.info(
                                f"🔄 Rewriting internal redirect: {location} -> {new_location}"
                            )
                            response.headers["location"] = new_location
                            break
        return response

    # REMOVED: RBAC middleware - replaced with simple auth role checking
    logger.info("🔐 Using simple auth system - RBAC middleware removed")

    # REMOVED: Session persistence middleware - replaced with simple JWT auth
    logger.info("🔐 Using simple JWT auth - session persistence middleware removed")

    # Add extension authentication middleware
    @app.middleware("http")
    async def extension_auth_middleware(request: Request, call_next):
        """Extension-specific authentication middleware."""
        # Only apply to extension API endpoints
        if request.url.path.startswith("/api/extensions"):
            try:
                # Import here to avoid circular imports
                from server.security import extension_auth_manager

                # Skip authentication for health endpoints
                if request.url.path.endswith("/health") or request.url.path.endswith(
                    "/system/health"
                ):
                    response = await call_next(request)
                    return response

                # Skip authentication for OPTIONS requests (CORS preflight)
                if request.method == "OPTIONS":
                    response = await call_next(request)
                    return response

                # For extension endpoints, ensure authentication context is available
                # The actual authentication will be handled by the endpoint dependencies
                # This middleware just adds logging and context preparation

                logger.debug(
                    f"Extension API request: {request.method} {request.url.path}"
                )

                # Add request metadata for extension authentication
                request.state.extension_api = True
                request.state.auth_required = True

                response = await call_next(request)
                return response

            except Exception as e:
                logger.error(f"Extension authentication middleware error: {e}")
                # Don't block the request, let endpoint handle authentication
                response = await call_next(request)
                return response
        else:
            # Non-extension endpoints, proceed normally
            response = await call_next(request)
            return response

    # Configure and register enhanced rate limiting middleware
    from ai_karen_engine.middleware.rate_limit import configure_rate_limiter

    # Check if rate limiting is enabled globally
    enable_rate_limiting = os.getenv("ENABLE_RATE_LIMITING", "false").lower() in (
        "1",
        "true",
        "yes",
    )

    if enable_rate_limiting:
        # Configure rate limiter based on environment
        storage_type = "memory"  # Default to memory storage
        redis_url = None

        # Try to get Redis configuration from environment
        if os.getenv("REDIS_URL"):
            storage_type = "redis"
            redis_url = os.getenv("REDIS_URL")
        elif os.getenv("RATE_LIMIT_REDIS_URL"):
            storage_type = "redis"
            redis_url = os.getenv("RATE_LIMIT_REDIS_URL")

        configure_rate_limiter(storage_type=storage_type, redis_url=redis_url)

        # Register enhanced rate limiting middleware - disabled in bypass mode
        auth_mode = os.getenv("AUTH_MODE", "hybrid").lower()
        if auth_mode != "bypass":
            app.middleware("http")(rate_limit_middleware)
        else:
            logger.info("🔓 Skipping rate limiting middleware - AUTH_MODE=bypass")
    else:
        logger.info(
            "🔓 Rate limiting disabled via ENABLE_RATE_LIMITING environment variable"
        )
    # Temporarily disabled to fix runaway usage counter loop
    # app.middleware("http")(error_counter_middleware)

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/copilot/assist"):
            logger.warning(
                "security_headers_middleware received response: %s",
                type(response).__name__ if response is not None else "None",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        env_name = (getattr(settings, "environment", "") or "").lower()
        is_production = env_name == "production"

        if is_production:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self'"
            )
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self)"
        else:
            # Development: permissive CSP to allow cross-port API calls
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' http://localhost:* http://127.0.0.1:*; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https: http:; "
                "font-src 'self' data:; "
                "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*"
            )
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self)"
        return response

    # Use globally configured validation framework or create default
    import sys

    current_module = sys.modules[__name__]
    validation_config = getattr(current_module, "_validation_config", None)
    enhanced_logger = getattr(current_module, "_enhanced_logger", None)

    if validation_config is None:
        # Fallback configuration if initialization failed
        validation_config = ValidationConfig(
            max_content_length=getattr(settings, "max_request_size", 10 * 1024 * 1024),
            log_invalid_requests=True,
            enable_security_analysis=True,
        )
        logger.warning("Using fallback validation configuration")

    # Ensure an enhanced logger is available even if initialization path was skipped
    if enhanced_logger is None:
        try:
            from ai_karen_engine.server.enhanced_logger import (
                EnhancedLogger,
                LoggingConfig,
            )

            default_logging_cfg = LoggingConfig(
                log_level="INFO",
                enable_security_logging=True,
                sanitize_data=True,
            )
            # Store on this module so other imports can find it
            import sys as _sys

            _mod = _sys.modules[__name__]
            setattr(_mod, "_enhanced_logger", EnhancedLogger(default_logging_cfg))
            enhanced_logger = getattr(_mod, "_enhanced_logger")
            logger.info("Enhanced logger initialized by middleware")
        except Exception:
            # Proceed without enhanced logger; fallback logging will be used
            pass

    http_validator = HTTPRequestValidator(validation_config)

    # Add canonical runtime logging middleware to bind async context and log lifecycle
    # We add it late in the configuration so it becomes one of the outermost middlewares,
    # ensuring it captures full request duration and all internal errors.
    app.add_middleware(RuntimeLoggingMiddleware)

    # Add intelligent error handler as the FINAL middleware (making it the outermost)
    # This ensures it catches errors from all other middlewares.
    app.add_middleware(
        IntelligentErrorHandlerMiddleware,
        enable_intelligent_responses=True,
        debug_mode=getattr(settings, "environment", "").lower() != "production",
    )
