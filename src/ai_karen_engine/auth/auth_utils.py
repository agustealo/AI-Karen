"""Small authentication cookie helpers.

These functions adapt HTTP cookies/headers to the canonical auth middleware.
They never synthesize user or tenant identity.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response, status

COOKIE_NAME = "kari_session"


def _is_production() -> bool:
    env = (
        os.getenv("ENVIRONMENT")
        or os.getenv("KARI_ENV")
        or os.getenv("ENV")
        or "development"
    ).lower()
    return env == "production"


def get_session_token(request: Request) -> Optional[str]:
    """Extract the access/session token from the canonical cookie or bearer header."""

    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        resolved = auth_header.split(" ", 1)[1].strip()
        return resolved or None
    return None


def get_refresh_token(request: Request) -> Optional[str]:
    return request.cookies.get("refresh_token")


def set_session_cookie(
    response: Response,
    session_token: str,
    max_age: int = 24 * 60 * 60,
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=_is_production(),
        samesite="strict",
    )


def set_refresh_token_cookie(
    response: Response,
    refresh_token: str,
    expires_at: Optional[datetime] = None,
) -> None:
    max_age = 7 * 24 * 60 * 60
    if expires_at:
        max_age = max(0, int((expires_at - datetime.utcnow()).total_seconds()))
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=_is_production(),
        samesite="strict",
    )


def clear_auth_cookies(response: Response) -> None:
    secure = _is_production()
    for cookie_name in (COOKIE_NAME, "refresh_token"):
        response.set_cookie(
            cookie_name,
            "",
            max_age=0,
            httponly=True,
            secure=secure,
            samesite="strict",
        )


def validate_cookie_security() -> Dict[str, Any]:
    return {
        "status": "configured",
        "secure_cookies": _is_production(),
        "httponly": True,
        "samesite": "strict",
    }


async def get_current_user(request: Request) -> Dict[str, Any]:
    """Resolve authenticated identity through the canonical auth middleware."""

    try:
        from ai_karen_engine.auth.auth_middleware import get_auth_middleware

        user_data = await get_auth_middleware().authenticate_request(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc

    user_id = str(user_data.get("user_id") or "").strip()
    tenant_id = str(user_data.get("tenant_id") or "").strip()
    if not user_id or user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authoritative tenant context required",
        )
    return user_data
