"""Canonical FastAPI exception translation for AI KAREN.

Exception handlers return transport error envelopes only. They must never
fabricate assistant answers, providers, models, or successful status codes for
failed runtime execution.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_karen_engine.auth.auth_middleware import AuthenticationError
from ai_karen_engine.server.json_encoder import custom_json_dumps

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_response(
    *,
    status_code: int,
    content: Dict[str, Any],
    headers: Dict[str, str] | None = None,
) -> JSONResponse:
    """Serialize through the canonical encoder and fail safely if needed."""
    try:
        serialized = custom_json_dumps(content)
        return JSONResponse(
            status_code=status_code,
            content=json.loads(serialized),
            headers=headers,
        )
    except Exception:
        logger.exception("Failed to serialize exception response")
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": "Unable to serialize error response",
                "error_code": "ERROR_RESPONSE_SERIALIZATION_FAILED",
                "timestamp": _timestamp(),
            },
            headers=headers,
        )


async def custom_http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    content: Dict[str, Any] = {"detail": exc.detail}
    if logger.isEnabledFor(logging.DEBUG):
        content.update(
            {
                "timestamp": _timestamp(),
                "path": str(request.url.path),
                "method": request.method,
            }
        )
    return _json_response(
        status_code=exc.status_code,
        content=content,
        headers=dict(exc.headers or {}),
    )


async def custom_starlette_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return await custom_http_exception_handler(
        request,
        HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
            headers=getattr(exc, "headers", None),
        ),
    )


async def custom_validation_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.warning(
        "Request validation failed",
        extra={"method": request.method, "path": str(request.url.path)},
    )
    return _json_response(
        status_code=422,
        content={
            "detail": "Validation error",
            "message": str(exc),
            "timestamp": _timestamp(),
            "path": str(request.url.path),
            "method": request.method,
        },
    )


async def custom_general_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled request exception",
        extra={"method": request.method, "path": str(request.url.path)},
    )

    content: Dict[str, Any] = {
        "detail": "Internal server error",
        "message": "An unexpected error occurred",
        "error_code": "INTERNAL_SERVER_ERROR",
        "timestamp": _timestamp(),
        "path": str(request.url.path),
        "method": request.method,
    }
    if logger.isEnabledFor(logging.DEBUG):
        content.update(
            {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
        )

    return _json_response(status_code=500, content=content)


async def custom_authentication_exception_handler(
    request: Request,
    exc: AuthenticationError,
) -> JSONResponse:
    status_code = int(getattr(exc, "status_code", 401))
    message = str(getattr(exc, "message", str(exc)))
    logger.warning(
        "Authentication request rejected",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status_code": status_code,
        },
    )
    return _json_response(
        status_code=status_code,
        content={
            "detail": message,
            "timestamp": _timestamp(),
            "path": str(request.url.path),
            "method": request.method,
        },
    )


def setup_exception_handlers(app) -> None:
    """Register canonical exception handlers."""
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.add_exception_handler(
        StarletteHTTPException,
        custom_starlette_http_exception_handler,
    )
    app.add_exception_handler(
        RequestValidationError,
        custom_validation_exception_handler,
    )
    app.add_exception_handler(
        AuthenticationError,
        custom_authentication_exception_handler,
    )
    app.add_exception_handler(Exception, custom_general_exception_handler)

    logger.info("Canonical exception handlers registered")
