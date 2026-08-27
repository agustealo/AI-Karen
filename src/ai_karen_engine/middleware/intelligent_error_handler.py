"""Global structured error handling middleware.

The middleware may enrich an error envelope with operational guidance, but it
must never fabricate assistant output, provider identity, model identity, or a
successful response status for a failed execution path.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ai_karen_engine.services.error_response_service import ErrorResponseService

logger = logging.getLogger(__name__)


class IntelligentErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Translate transport failures into consistent structured error envelopes."""

    def __init__(
        self,
        app,
        enable_intelligent_responses: bool = True,
        debug_mode: bool = False,
    ) -> None:
        super().__init__(app)
        self.enable_intelligent_responses = enable_intelligent_responses
        self.debug_mode = debug_mode
        self._error_response_service: Optional[ErrorResponseService] = None
        self.simple_error_paths = {
            "/api/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        }

    def _get_error_response_service(self) -> Optional[ErrorResponseService]:
        if not self.enable_intelligent_responses:
            return None
        if self._error_response_service is None:
            try:
                self._error_response_service = ErrorResponseService()
            except Exception:
                logger.exception("Failed to initialize error response service")
        return self._error_response_service

    def _should_use_simple_error(self, request: Request) -> bool:
        path = request.url.path
        return any(path == prefix or path.startswith(prefix) for prefix in self.simple_error_paths)

    @staticmethod
    def _extract_request_metadata(request: Request) -> Dict[str, str]:
        forwarded_for = request.headers.get("x-forwarded-for")
        ip_address = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else "unknown")
        )
        return {
            "ip_address": ip_address,
            "user_agent": request.headers.get("user-agent", ""),
            "path": request.url.path,
            "method": request.method,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_provider_from_error(
        error_message: str,
        traceback_str: str,
    ) -> Optional[str]:
        """Classify provider-related errors for diagnostics only."""
        provider_patterns = {
            "openai": ("openai", "gpt", "chatgpt"),
            "anthropic": ("anthropic", "claude"),
            "huggingface": ("huggingface", "transformers"),
            "groq": ("groq",),
            "cohere": ("cohere",),
        }
        haystack = f"{error_message} {traceback_str}".lower()
        for provider, patterns in provider_patterns.items():
            if any(pattern in haystack for pattern in patterns):
                return provider
        return None

    async def _create_simple_error_response(
        self,
        *,
        error_message: str,
        status_code: int,
        traceback_str: Optional[str] = None,
    ) -> JSONResponse:
        response_data: Dict[str, object] = {"detail": error_message}
        if self.debug_mode and traceback_str:
            response_data["traceback"] = traceback_str
        return JSONResponse(content=response_data, status_code=status_code)

    async def _create_intelligent_error_response(
        self,
        *,
        error_message: str,
        error_type: str,
        status_code: int,
        request_meta: Dict[str, str],
        traceback_str: Optional[str] = None,
    ) -> JSONResponse:
        error_service = self._get_error_response_service()
        if error_service is None:
            return await self._create_simple_error_response(
                error_message=error_message,
                status_code=status_code,
                traceback_str=traceback_str,
            )

        try:
            provider_name = self._extract_provider_from_error(
                error_message,
                traceback_str or "",
            )
            analysis = error_service.analyze_error(
                error_message=error_message,
                error_type=error_type,
                status_code=status_code,
                provider_name=provider_name,
                additional_context={
                    **request_meta,
                    "traceback": traceback_str if self.debug_mode else None,
                },
            )

            error_payload: Dict[str, object] = {
                "title": analysis.title,
                "category": analysis.category,
                "severity": analysis.severity,
                "next_steps": analysis.next_steps,
                "contact_admin": analysis.contact_admin,
                "retry_after": analysis.retry_after,
                "help_url": analysis.help_url,
                "timestamp": request_meta["timestamp"],
            }
            if analysis.provider_health:
                error_payload["provider_health"] = analysis.provider_health
            if self.debug_mode and analysis.technical_details:
                error_payload["technical_details"] = analysis.technical_details
            if self.debug_mode and traceback_str:
                error_payload["traceback"] = traceback_str

            headers: Dict[str, str] = {}
            if analysis.retry_after:
                headers["Retry-After"] = str(analysis.retry_after)

            return JSONResponse(
                content={
                    "detail": analysis.summary,
                    "error": error_payload,
                },
                status_code=status_code,
                headers=headers,
            )
        except Exception:
            logger.exception("Failed to generate structured error analysis")
            return await self._create_simple_error_response(
                error_message=error_message,
                status_code=status_code,
                traceback_str=traceback_str,
            )

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        request_meta = self._extract_request_metadata(request)
        try:
            response = await call_next(request)
            if response is None:
                raise RuntimeError("No response returned from inner middleware chain")
            return response
        except HTTPException as exc:
            logger.info(
                "HTTP exception",
                extra={
                    "status_code": exc.status_code,
                    "path": request_meta["path"],
                    "method": request_meta["method"],
                    "ip_address": request_meta["ip_address"],
                },
            )
            if self._should_use_simple_error(request):
                return await self._create_simple_error_response(
                    error_message=str(exc.detail),
                    status_code=exc.status_code,
                )
            return await self._create_intelligent_error_response(
                error_message=str(exc.detail),
                error_type="http_exception",
                status_code=exc.status_code,
                request_meta=request_meta,
            )
        except Exception as exc:
            error_message = str(exc).strip() or "Internal server error"
            error_type = type(exc).__name__
            traceback_str = traceback.format_exc()
            logger.exception(
                "Unhandled middleware exception",
                extra={
                    "error_type": error_type,
                    "path": request_meta["path"],
                    "method": request_meta["method"],
                    "ip_address": request_meta["ip_address"],
                },
            )

            if self._should_use_simple_error(request):
                return await self._create_simple_error_response(
                    error_message="Internal server error",
                    status_code=500,
                    traceback_str=traceback_str,
                )
            return await self._create_intelligent_error_response(
                error_message=error_message,
                error_type=error_type,
                status_code=500,
                request_meta=request_meta,
                traceback_str=traceback_str,
            )


def add_intelligent_error_handler(
    app,
    enable_intelligent_responses: bool = True,
    debug_mode: bool = False,
) -> None:
    """Register the global structured error handler."""
    app.add_middleware(
        IntelligentErrorHandlerMiddleware,
        enable_intelligent_responses=enable_intelligent_responses,
        debug_mode=debug_mode,
    )
