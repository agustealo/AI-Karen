"""
Platform Error Middleware for AI-Karen

HTTP error middleware moved out of Core per CORE-SPLIT-2.
Core must not import HTTP middleware.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ai_karen_engine.core.errors.exceptions import KarenError


class PlatformErrorMiddleware:
    """Platform-level error middleware."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        try:
            await self.app(scope, receive, send)
        except KarenError as exc:
            await self._handle_error(scope, receive, send, exc)
        except Exception as exc:
            await self._handle_unexpected_error(scope, receive, send, exc)

    async def _handle_error(self, scope: Dict[str, Any], receive: Callable, send: Callable, exc: KarenError) -> None:
        response = {
            "type": "http.response.start",
            "status": getattr(exc, "status_code", 500),
            "headers": [[b"content-type", b"application/json"]],
        }
        await send(response)
        await send({
            "type": "http.response.body",
            "body": f'{{"error": "{exc!s}"}}'.encode(),
        })

    async def _handle_unexpected_error(self, scope: Dict[str, Any], receive: Callable, send: Callable, exc: Exception) -> None:
        response = {
            "type": "http.response.start",
            "status": 500,
            "headers": [[b"content-type", b"application/json"]],
        }
        await send(response)
        await send({
            "type": "http.response.body",
            "body": b'{"error": "Internal server error"}',
        })
