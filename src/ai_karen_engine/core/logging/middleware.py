from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    clear_correlation_context,
    set_correlation_context,
)
# TODO: Fix emitter import
# from ai_karen_engine.core.observability.emitter import get_observability_emitter

from .context import RuntimeLogContext, clear_log_context, set_log_context
from .events import RuntimeEvents
from .logger import get_logger

logger = get_logger("kari.middleware")


class RuntimeLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to bind request context and log request lifecycle."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Create context
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # Determine client IP hash for privacy
        client_ip = request.client.host if request.client else "0.0.0.0"
        client_ip_hash = f"hash_{client_ip[-4:]}"

        log_ctx = RuntimeLogContext(
            correlation_id=correlation_id,
            request_id=request_id,
            route=request.url.path,
            method=request.method,
            client_ip_hash=client_ip_hash,
            runtime_stage="ingress",
        )

        obs_ctx = CorrelationContext(
            correlation_id=correlation_id,
            request_id=request_id,
        )

        log_token = set_log_context(log_ctx)
        obs_token = set_correlation_context(obs_ctx)
        # TODO: Fix emitter
        # emitter = get_observability_emitter()
        # emitter.emit(
        #     RuntimeEvents.REQUEST_STARTED,
        #     route=request.url.path,
        #     method=request.method,
        # )

        # Also attach to request state for downstream convenience
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        start_time = time.perf_counter()
        logger.event(RuntimeEvents.REQUEST_STARTED)

        try:
            # 3. Process request
            response = await call_next(request)

            # Update context with response info
            duration_ms = (time.perf_counter() - start_time) * 1000
            log_ctx.status = str(response.status_code)
            log_ctx.latency_ms = duration_ms

            logger.event(RuntimeEvents.REQUEST_COMPLETED)
            # TODO: Fix emitter
            # emitter.emit(
            #     RuntimeEvents.REQUEST_COMPLETED,
            #     status=str(response.status_code),
            #     duration_ms=duration_ms,
            # )

            # Add correlation header to response
            response.headers["X-Correlation-ID"] = correlation_id
            return response

        except Exception as exc:
            # Handle failure
            duration_ms = (time.perf_counter() - start_time) * 1000
            log_ctx.status = "500"
            log_ctx.latency_ms = duration_ms
            log_ctx.error_type = exc.__class__.__name__

            logger.exception(RuntimeEvents.REQUEST_FAILED)
            # TODO: Fix emitter
            # emitter.emit(
            #     RuntimeEvents.REQUEST_FAILED,
            #     status="500",
            #     duration_ms=duration_ms,
            #     error_type=exc.__class__.__name__,
            # )
            raise

        finally:
            # 4. Cleanup
            clear_log_context()
            clear_correlation_context()
