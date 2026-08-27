"""Canonical HTTP middleware composition for AI KAREN.

Middleware owns transport concerns only. It must not fabricate model output,
provider identity, tenant identity, persistence success, or deployment routing.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterable, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import StreamingResponse

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.logging.middleware import RuntimeLoggingMiddleware
from ai_karen_engine.middleware.intelligent_error_handler import (
    IntelligentErrorHandlerMiddleware,
)
from ai_karen_engine.middleware.rate_limit import (
    configure_rate_limiter,
    rate_limit_middleware,
)

logger = get_logger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value.split(","):
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _configured_cors_origins(settings: Any) -> list[str]:
    source = (
        os.getenv("CORS_ORIGINS")
        or os.getenv("KARI_CORS_ORIGINS")
        or getattr(settings, "kari_cors_origins", "")
        or ""
    )
    return _csv_values(source)


def _cors_regex(settings: Any) -> Optional[str]:
    configured = os.getenv("CORS_ALLOW_ORIGIN_REGEX")
    if configured:
        return configured

    environment = str(getattr(settings, "environment", "") or "").lower()
    if _env_flag("ALLOW_DEV_ORIGINS") or environment in {
        "development",
        "dev",
        "local",
    }:
        return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    return None


def _record_metric(metric, method: str, path: str, **labels: str) -> None:
    """Best-effort observability must never alter request semantics."""
    try:
        metric.labels(method=method, path=path, **labels).inc()
    except Exception:
        logger.debug("HTTP metric emission failed", exc_info=True)


def _observe_latency(metric, method: str, path: str, duration: float) -> None:
    try:
        metric.labels(method=method, path=path).observe(duration)
    except Exception:
        logger.debug("HTTP latency metric emission failed", exc_info=True)


def _apply_security_headers(response, *, production: bool) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self)"

    if production:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )


def _configure_rate_limiting(app: FastAPI) -> None:
    if not _env_flag("ENABLE_RATE_LIMITING"):
        logger.info("Rate limiting disabled by configuration")
        return

    redis_url = os.getenv("RATE_LIMIT_REDIS_URL") or os.getenv("REDIS_URL")
    storage_type = "redis" if redis_url else "memory"
    configure_rate_limiter(storage_type=storage_type, redis_url=redis_url)

    auth_mode = os.getenv("AUTH_MODE", "production").strip().lower()
    if auth_mode == "bypass":
        logger.warning("Rate limiting disabled because AUTH_MODE=bypass")
        return

    app.middleware("http")(rate_limit_middleware)


def configure_middleware(
    app: FastAPI,
    settings: Any,
    request_count,
    request_latency,
    error_count,
) -> None:
    """Register canonical transport middleware in deterministic order."""
    environment = str(getattr(settings, "environment", "") or "").lower()
    production = environment == "production"

    if getattr(settings, "https_redirect", False):
        app.add_middleware(HTTPSRedirectMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_configured_cors_origins(settings),
        allow_origin_regex=_cors_regex(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-Correlation-Id",
            "X-Response-Time",
            "X-Process-Time",
        ],
        max_age=600,
    )
    app.add_middleware(GZipMiddleware, minimum_size=5000, compresslevel=5)

    @app.middleware("http")
    async def prometheus_metrics_middleware(request: Request, call_next):
        method = request.method
        path = request.url.path
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.perf_counter() - started
            _record_metric(
                request_count,
                method,
                path,
                status="500",
            )
            _observe_latency(request_latency, method, path, duration)
            _record_metric(
                error_count,
                method,
                path,
                error_type=type(exc).__name__,
            )
            raise

        duration = time.perf_counter() - started
        status = str(response.status_code)
        _record_metric(request_count, method, path, status=status)
        _observe_latency(request_latency, method, path, duration)
        if response.status_code >= 400:
            _record_metric(error_count, method, path, error_type=status)
        return response

    @app.middleware("http")
    async def streaming_header_middleware(request: Request, call_next):
        response = await call_next(request)
        if isinstance(response, StreamingResponse):
            response.headers.pop("content-length", None)
        elif response.headers.get("content-encoding", "").lower() in {
            "gzip",
            "br",
            "deflate",
        }:
            response.headers.pop("content-length", None)
        return response

    @app.middleware("http")
    async def extension_context_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/extensions"):
            request.state.extension_api = True
            request.state.auth_required = True
        return await call_next(request)

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        _apply_security_headers(response, production=production)
        return response

    _configure_rate_limiting(app)

    app.add_middleware(RuntimeLoggingMiddleware)
    app.add_middleware(
        IntelligentErrorHandlerMiddleware,
        enable_intelligent_responses=True,
        debug_mode=not production,
    )
