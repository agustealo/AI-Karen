import os
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Response, status

def _is_production() -> bool:
    env = (
        os.getenv("ENVIRONMENT")
        or os.getenv("KARI_ENV")
        or os.getenv("ENV")
        or "development"
    ).lower()
    return env == "production"

# Legacy cookie name for backward compatibility
COOKIE_NAME = "kari_session"


def get_session_token(request: Request) -> Optional[str]:
    """Extract session token from cookies or Authorization header (simplified)."""
    # Try legacy cookie name
    token = request.cookies.get(COOKIE_NAME)
    
    # Fallback to Authorization header
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
    
    return token


def get_refresh_token(request: Request) -> Optional[str]:
    """Extract refresh token from secure HttpOnly cookies (simplified)."""
    return request.cookies.get("refresh_token")


def set_session_cookie(
    response: Response, session_token: str, max_age: int = 24 * 60 * 60
) -> None:
    """Set the authentication session cookie on the response (simplified)."""
    secure_flag = _is_production()
    response.set_cookie(
        COOKIE_NAME,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure_flag,
        samesite="strict",
    )


def set_refresh_token_cookie(
    response: Response, refresh_token: str, expires_at: Optional[datetime] = None
) -> None:
    """Set secure refresh token cookie with proper security flags (simplified)."""
    max_age = 7 * 24 * 60 * 60  # 7 days
    if expires_at:
        max_age = int((expires_at - datetime.utcnow()).total_seconds())
    
    secure_flag = _is_production()
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=secure_flag,
        samesite="strict",
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear all authentication cookies for logout (simplified)."""
    response.set_cookie(
        COOKIE_NAME,
        "",
        max_age=0,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    response.set_cookie(
        "refresh_token",
        "",
        max_age=0,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def validate_cookie_security() -> Dict[str, Any]:
    """Validate current cookie security configuration (simplified)."""
    return {
        "status": "simplified",
        "secure_cookies": _is_production(),
        "httponly": True,
        "samesite": "strict"
    }


async def get_current_user(request: Request) -> Dict[str, Any]:
    """FastAPI dependency to retrieve the current authenticated user using simple auth."""
    try:
        from ai_karen_engine.auth.auth_middleware import get_auth_middleware
        auth_middleware = get_auth_middleware()
        
        user_data = await auth_middleware.authenticate_request(request)
        if user_data:
            # Ensure tenant_id exists for compatibility
            if "tenant_id" not in user_data:
                user_data["tenant_id"] = "default"
            return user_data
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
