"""Middleware to track error responses in usage counters."""

# mypy: ignore-errors

try:
    from fastapi import Request
    from fastapi.responses import Response
except Exception:  # pragma: no cover - fallback for tests
    from ai_karen_engine.fastapi_stub import Request, Response

from ai_karen_engine.services.usage.service import UsageService


async def error_counter_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            user = getattr(request.state, "user", None)
            UsageService.increment("errors", user_id=user)
        return response
    except Exception:
        user = getattr(request.state, "user", None)
        UsageService.increment("errors", user_id=user)
        raise
