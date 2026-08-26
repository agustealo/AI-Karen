"""
Production Authentication Routes

Enhanced authentication endpoints with security hardening, rate limiting,
and first-run setup flow.
"""

import logging
import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user as get_authenticated_user
from ai_karen_engine.auth.rbac_middleware import get_rbac_manager
from ai_karen_engine.auth.auth_middleware import get_rate_limiter
from ai_karen_engine.services.auth.auth_service import (
    AuthService as CoreAuthService,
    UserRole,
)
from ai_karen_engine.database.dependencies import get_async_db_session_dependency

# AuthService is imported locally where needed to avoid circular imports

logger = logging.getLogger("kari.auth_routes")


def _has_role(current_user: Any, role: str) -> bool:
    """Case-insensitive role check for route authorization."""
    roles = getattr(current_user, "roles", None)
    if roles is None and isinstance(current_user, dict):
        roles = current_user.get("roles", [])
    return any(str(item).strip().lower() == role.lower() for item in (roles or []))


# Request/Response Models
class LoginRequest(BaseModel):
    """Login request model."""

    email: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_login_identifier(self):
        """Ensure either email or username is provided."""
        if not self.email and not self.username:
            raise ValueError("Either email or username must be provided")
        return self


class LoginResponse(BaseModel):
    """Login response model."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]
    permissions: List[str]


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""

    refresh_token: str


class FirstRunSetupRequest(BaseModel):
    """First-run admin setup request."""

    email: str
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1)
    confirm_password: str = Field(..., min_length=8)


class CreateUserRequest(BaseModel):
    """Create user request model."""

    email: str
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1)
    roles: Optional[list] = Field(default=["user"])


class UserResponse(BaseModel):
    """User response model."""

    user_id: str
    email: str
    username: str
    full_name: str
    roles: list
    is_active: bool
    created_at: str
    last_login: Optional[str]
    tenant_id: str
    preferences: Dict[str, Any]


class UpdateProfileRequest(BaseModel):
    """Update the current user's profile."""

    email: Optional[str] = None
    username: Optional[str] = Field(default=None, min_length=1)
    full_name: Optional[str] = Field(default=None, min_length=1)
    preferences: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_payload(self):
        if (
            self.email is None
            and self.username is None
            and self.full_name is None
            and self.preferences is None
        ):
            raise ValueError("At least one profile field must be provided")
        return self


class ChangePasswordRequest(BaseModel):
    """Change the current user's password."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)
    confirm_password: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_passwords(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


# Initialize service with default configuration
# Global auth service instance for singleton usage
_auth_service_instance: Optional[CoreAuthService] = None
_auth_service_init_lock = asyncio.Lock()


async def get_auth_service(
    db_session: AsyncSession = Depends(get_async_db_session_dependency),
) -> CoreAuthService:
    """Get the singleton auth service instance with request-specific DB session."""
    global _auth_service_instance

    if _auth_service_instance is None:
        async with _auth_service_init_lock:
            if _auth_service_instance is None:
                logger.info("Creating singleton AuthService instance")
                _auth_service_instance = CoreAuthService()

    # CoreAuthService.initialize() has its own internal lock and is safe to call concurrently.
    # We call it here to ensure it's ready before use, without holding our local init lock.
    if not _auth_service_instance._initialized:
        await _auth_service_instance.initialize()

    # Set the request-specific session in ContextVar-safe way (via set_db_session)
    _auth_service_instance.set_db_session(db_session)
    return _auth_service_instance


# Router - now with explicit /auth prefix for API gateway consistency
router = APIRouter(prefix="/auth", tags=["authentication"])


def get_client_ip(request: Request) -> str:
    """Get client IP address from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """Get user agent from request."""
    return request.headers.get("User-Agent", "unknown")


def _serialize_permissions(user_payload: Dict[str, Any]) -> List[str]:
    """Resolve canonical permission strings for the authenticated user."""

    rbac_manager = get_rbac_manager()
    user = UserData.from_dict(user_payload)
    permissions = {
        permission.value if hasattr(permission, "value") else str(permission)
        for permission in rbac_manager.get_user_permissions(user)
    }
    return sorted(permissions)


def _user_value(user: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a dict payload or an object."""
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def _ensure_authenticated_user_payload(user: Any) -> Dict[str, Any]:
    """Normalize and validate an authenticated user payload."""
    if isinstance(user, dict):
        payload = dict(user)
    else:
        payload = {
            "user_id": getattr(user, "user_id", None) or getattr(user, "id", None),
            "email": getattr(user, "email", None),
            "username": getattr(user, "username", None),
            "full_name": getattr(user, "full_name", None),
            "roles": getattr(user, "roles", []),
            "tenant_id": getattr(user, "tenant_id", None),
            "preferences": getattr(user, "preferences", {}),
            "is_active": getattr(user, "is_active", True),
        }

    user_id = str(payload.get("user_id") or payload.get("id") or "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user context is missing a user identifier",
        )

    payload["user_id"] = user_id
    payload["tenant_id"] = str(
        payload.get("tenant_id") or payload.get("org_id") or "default"
    )
    payload["roles"] = list(payload.get("roles") or [])
    payload["preferences"] = dict(payload.get("preferences") or {})
    # Generate default username from email if not provided
    username = payload.get("username") or ""
    if not username and payload.get("email"):
        username = payload["email"].split("@")[0]
    payload["username"] = username

    payload["full_name"] = payload.get("full_name") or payload.get("name") or ""
    payload["email"] = payload.get("email") or ""
    return payload


def _serialize_user_response(user: Any) -> Dict[str, Any]:
    """Normalize a user-like object into the public response shape."""
    payload = _ensure_authenticated_user_payload(user)
    user_id = payload["user_id"]
    created_at = _user_value(user, "created_at", None)
    last_login = _user_value(user, "last_login", None)
    tenant_id = payload["tenant_id"]
    status_value = _user_value(user, "status", None)
    is_active = (
        getattr(status_value, "value", None) == "active"
        if status_value is not None
        else bool(payload.get("is_active", True))
    )

    return {
        "user_id": user_id,
        "email": payload["email"],
        "username": payload["username"],
        "full_name": payload["full_name"],
        "roles": payload["roles"],
        "is_active": is_active,
        "created_at": created_at.isoformat()
        if created_at
        else datetime.now(timezone.utc).isoformat(),
        "last_login": last_login.isoformat() if last_login else None,
        "tenant_id": tenant_id,
        "preferences": payload["preferences"],
    }


def _resolve_current_user_id(user: Any) -> str:
    """Resolve current user ID from either a dict payload or a user-like object."""
    payload = _ensure_authenticated_user_payload(user)
    return payload["user_id"]


def _require_tenant_scope(user: Any) -> str:
    """Return an explicit tenant scope for tenant-admin operations."""
    tenant_id = str(_user_value(user, "tenant_id", "") or "").strip()
    if not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explicit tenant scope is required for this operation",
        )
    return tenant_id


# Startup/shutdown handlers commented out to prevent blocking during app startup
# The AuthService is already initialized when the module loads
# @router.on_event("startup")
# async def startup_auth_service():
#     """Initialize authentication service on startup."""
#     await auth_service.initialize()
#     await auth_service.start()


# @router.on_event("shutdown")
# async def shutdown_auth_service():
#     """Shutdown authentication service."""
#     await auth_service.stop()


@router.get("/status")
async def auth_status(
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Get authentication service status."""
    stats = await auth_svc.get_auth_stats()

    return {
        "status": "healthy",
        "service": "production-auth",
        "mode": "jwt-authentication",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "features": {
            "authentication": True,
            "authorization": True,
            "rate_limiting": True,
            "account_lockout": True,
            "password_strength": True,
            "audit_logging": True,
        },
        "stats": stats,
    }


@router.get("/health")
async def auth_health(
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Authentication service health check."""
    is_healthy = await auth_svc.health_check()

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "service": "production-auth",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/first-run")
async def check_first_run(
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Check if first-run setup is required."""
    try:
        is_first_run = await auth_svc.is_first_run()
    except Exception:
        logger.exception("Unable to determine first-run state")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="First-run state unavailable",
        )

    return {
        "first_run_required": is_first_run,
        "message": "First-run setup required"
        if is_first_run
        else "System already configured",
    }


@router.post("/first-run/setup")
async def first_run_setup(
    request: FirstRunSetupRequest,
    http_request: Request,
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> JSONResponse:
    """Set up the first admin user through the canonical auth authority."""

    # Validate password confirmation
    if request.password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match"
        )

    try:
        user = await auth_svc.create_first_admin(
            email=request.email,
            password=request.password,
            full_name=request.full_name,
        )

        # Authenticate the new admin user
        ip_address = get_client_ip(http_request)
        user_agent = get_user_agent(http_request)

        auth_user, access_token, refresh_token = await auth_svc.authenticate_user(
            request.email,
            request.password,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if not auth_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to authenticate newly created admin user",
            )

        # Return login response
        user_data = {
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "roles": user.roles,
            "is_active": user.status.value == "active",
            "tenant_id": user.tenant_id,
            "preferences": user.preferences,
        }

        permissions = _serialize_permissions(user_data)
        user_data["permissions"] = permissions

        response_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": auth_svc.config.access_token_expire_minutes * 60,
            "user": user_data,
            "permissions": permissions,
            "message": "First admin user created and authenticated successfully",
        }

        response = JSONResponse(
            content=response_data, status_code=status.HTTP_201_CREATED
        )

        is_secure = http_request.url.scheme == "https"
        response.set_cookie(
            key="kari_session",
            value=access_token or "",
            max_age=auth_svc.config.access_token_expire_minutes * 60,
            httponly=True,
            secure=is_secure,
            samesite="lax",
            path="/",
        )

        return response

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create first admin user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create admin user",
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    auth_svc: CoreAuthService = Depends(get_auth_service),
    limiter: Any = Depends(get_rate_limiter),
) -> JSONResponse:
    """Authenticate user and return tokens."""
    ip_address = get_client_ip(http_request)
    user_agent = get_user_agent(http_request)

    # Determine login identifier (email or username)
    login_identifier = request.email or request.username or ""

    # Check rate limit before proceeding
    if not limiter._check_rate_limit(login_identifier, "login_attempts"):
        logger.warning(f"Rate limit exceeded for login attempts: {login_identifier}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    logger.info(f"Login attempt for identifier: {login_identifier}")

    try:
        coro = auth_svc.authenticate_user(
            login_identifier,  # positional string
            request.password,  # positional string
            ip_address=ip_address,
            user_agent=user_agent,
        )
        user, access_token, refresh_token_or_error = await coro
        logger.info(f"Authenticate user succeeded: user={user is not None}")
    except Exception as e:
        logger.error(f"Exception in authenticate_user: {e}", exc_info=True)
        raise

    if not user:
        # Record failed attempt for rate limiting
        limiter._record_failed_attempt(
            login_identifier, "login_attempts", refresh_token_or_error
        )
        # refresh_token_or_error contains error message
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=refresh_token_or_error,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Guard against None access_token (should not happen when user is not None)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate access token",
        )

    user_data = {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "roles": user.roles,
        "is_active": user.status.value == "active",
        "tenant_id": user.tenant_id,
        "preferences": user.preferences,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }
    permissions = _serialize_permissions(user_data)
    user_data["permissions"] = permissions

    response_data = {
        "access_token": access_token,
        "refresh_token": refresh_token_or_error,  # This is refresh_token on success
        "token_type": "bearer",
        "expires_in": auth_svc.config.access_token_expire_minutes * 60,
        "user": user_data,
        "permissions": permissions,
    }
    response = JSONResponse(content=response_data)

    # Determine if we should use secure cookies (HTTPS only)
    is_secure = http_request.url.scheme == "https"

    # Set the kari_session cookie with the access token
    # This allows the auth middleware to authenticate requests via cookie
    response.set_cookie(
        key="kari_session",
        value=access_token,
        max_age=auth_svc.config.access_token_expire_minutes * 60,  # Convert to seconds
        httponly=True,  # Prevent JavaScript access (XSS protection)
        secure=is_secure,  # Only send over HTTPS in production
        samesite="lax",  # CSRF protection while allowing navigation
        path="/",  # Available for all routes
    )

    return response


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    http_request: Request,
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> JSONResponse:
    """Rotate the refresh token and return a fresh token pair."""
    access_token, new_refresh_token, error = await auth_svc.refresh_access_token(
        request.refresh_token
    )

    if not access_token or not new_refresh_token:
        status_code = status.HTTP_401_UNAUTHORIZED
        if error == "Database unavailable":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            logger.warning("Refresh token rotation unavailable because database is unavailable")

        raise HTTPException(
            status_code=status_code,
            detail=error,
            headers={"WWW-Authenticate": "Bearer"},
        )

    response_data = {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": auth_svc.config.access_token_expire_minutes * 60,
    }

    response = JSONResponse(content=response_data)
    response.set_cookie(
        key="kari_session",
        value=access_token,
        max_age=auth_svc.config.access_token_expire_minutes * 60,
        httponly=True,
        secure=http_request.url.scheme == "https",
        samesite="lax",
        path="/",
    )

    return response


@router.post("/logout")
async def logout(
    request: RefreshTokenRequest,
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> JSONResponse:
    await auth_svc.logout(request.refresh_token)

    response = JSONResponse(content={"detail": "Successfully logged out"})
    response.delete_cookie("kari_session", path="/")
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response


@router.get("/validate-session")
async def validate_session(
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Validate current session and return user information."""
    current_user_id = _resolve_current_user_id(current_user)
    canonical_user = await auth_svc.get_user_by_id(current_user_id)
    if canonical_user is not None:
        user_payload = _serialize_user_response(canonical_user)
    else:
        # Fallback to middleware-provided context if canonical lookup fails.
        user_payload = _ensure_authenticated_user_payload(current_user)
    permissions = _serialize_permissions(user_payload)
    user_payload["permissions"] = permissions
    is_authenticated = current_user.get("authenticated", False)
    return {
        "valid": True,
        "user": user_payload,
        "permissions": permissions,
        "authenticated": is_authenticated,
        "session_valid": is_authenticated,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Get current user information."""
    current_user_id = _resolve_current_user_id(current_user)
    canonical_user = await auth_svc.get_user_by_id(current_user_id)
    response = (
        _serialize_user_response(canonical_user)
        if canonical_user is not None
        else _serialize_user_response(current_user)
    )
    response["authenticated"] = True
    response["last_active"] = datetime.now(timezone.utc).isoformat()
    return response


@router.put("/test")
async def test_put_endpoint() -> Dict[str, Any]:
    """Simple test endpoint to check if PUT works."""
    return {"message": "PUT endpoint works"}


@router.put("/me")
async def update_current_user_info(
    request: UpdateProfileRequest,
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Update current user information."""

    try:
        current_user_id = _resolve_current_user_id(current_user)
        logger.info(f"PUT /me called for user_id: {current_user_id}")

        logger.info(f"Using auth_service for user {current_user_id}")
        updated_user, error = await auth_svc.update_user_profile(
            current_user_id,
            email=str(request.email) if request.email is not None else None,
            username=request.username,
            full_name=request.full_name,
            preferences=request.preferences,
        )

        if not updated_user:
            status_code = status.HTTP_400_BAD_REQUEST
            if error == "User not found":
                status_code = status.HTTP_404_NOT_FOUND
            elif error == "User with this email already exists":
                status_code = status.HTTP_409_CONFLICT

            debug_msg = (
                f"{error or 'Failed to update profile'} - ID was '{current_user_id}'"
            )
            logger.error(f"Profile update failed: {debug_msg}")
            raise HTTPException(status_code=status_code, detail=debug_msg)

        logger.info(f"Profile update successful for user {current_user_id}")
        return _serialize_user_response(updated_user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in PUT /me for user {current_user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user profile: {str(e)}",
        )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, str]:
    """Change the current user's password."""

    current_user_id = _resolve_current_user_id(current_user)

    error = await auth_svc.change_user_password(
        current_user_id,
        request.current_password,
        request.new_password,
    )

    if error:
        status_code = status.HTTP_400_BAD_REQUEST
        if error == "Current password is incorrect":
            status_code = status.HTTP_401_UNAUTHORIZED
        elif error == "User not found":
            status_code = status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=status_code, detail=error)

    response = JSONResponse(
        content={"detail": "Password updated successfully; sign in again"}
    )
    response.delete_cookie("kari_session", path="/")
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response


@router.post("/create-user", response_model=UserResponse)
async def create_user(
    request: CreateUserRequest,
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> JSONResponse:
    """Create a new user (admin only)."""
    # Check if current user has admin privileges
    if not _has_role(current_user, "admin") and not _has_role(current_user, "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient privileges to create users",
        )

    tenant_id = _require_tenant_scope(current_user)
    user, error = await auth_svc.create_user(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
        tenant_id=tenant_id,
        roles=request.roles,
    )

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    user_data = {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "roles": user.roles,
        "is_active": user.status.value == "active",
        "created_at": user.created_at.isoformat(),
        "last_login": None,
        "tenant_id": user.tenant_id,
        "preferences": user.preferences,
    }

    return JSONResponse(content=user_data, status_code=status.HTTP_201_CREATED)


@router.get("/stats", response_model=None)
async def get_auth_stats(
    current_user=Depends(get_authenticated_user),
    auth_svc: CoreAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Get authentication statistics (admin only)."""
    # Check if current user has admin privileges
    if not _has_role(current_user, "admin") and not _has_role(current_user, "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient privileges to view authentication statistics",
        )

    tenant_id = None
    if not _has_role(current_user, "super_admin"):
        tenant_id = _require_tenant_scope(current_user)
    stats = await auth_svc.get_auth_stats(tenant_id=tenant_id)
    return stats


@router.get("/security/context")
async def get_security_context(
    current_user=Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Get security context for authenticated user."""
    return {
        "userRoles": current_user.get("roles", []),
        "securityMode": "safe",  # Default to safe mode
        "canAccessSensitive": current_user.get("roles", []).intersection(
            ["admin", "super_admin"]
        )
        != set(),
        "redactionLevel": "partial",  # Default to partial redaction
    }