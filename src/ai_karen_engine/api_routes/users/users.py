import asyncio
from typing import Any, Dict, List, Optional

from ai_karen_engine.auth.auth_middleware import (
    get_current_user as bypass_user_context_func,
)
from ai_karen_engine.core.services.dependencies import get_analytics_service
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic
from ai_karen_engine.auth.auth_service import AuthService, get_auth_service
from ai_karen_engine.auth.exceptions import (
    AuthError,
    UserNotFoundError,
    UserAlreadyExistsError,
    RateLimitExceededError,
    SecurityError,
)

APIRouter, Depends, HTTPException, Response = import_fastapi(
    "APIRouter", "Depends", "HTTPException", "Response"
)
BaseModel = import_pydantic("BaseModel")

router = APIRouter()

# Global auth service instance (will be initialized lazily)
auth_service_instance: AuthService = None


async def get_auth_service_instance() -> AuthService:
    """Get the auth service instance, initializing it if necessary."""
    global auth_service_instance
    if auth_service_instance is None:
        auth_service_instance = await get_auth_service()
    return auth_service_instance


class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    tenant_id: str = "default"
    roles: Optional[List[str]] = None


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    roles: Optional[List[str]] = None
    preferences: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str]
    tenant_id: str
    roles: List[str]
    preferences: Dict[str, Any]
    is_active: bool
    is_verified: bool
    last_login: Optional[str] = None
    created_at: str
    updated_at: str


class ErrorResponse(BaseModel):
    detail: str


class UserMetricsResponse(BaseModel):
    user_id: str
    hours: int
    event_count: int
    session_count: int
    total_session_minutes: float
    average_session_minutes: float
    last_seen: Optional[str] = None
    token_usage: Optional[int] = None
    token_usage_supported: bool = False


def _normalize_roles(roles: Optional[List[str]]) -> List[str]:
    """Normalize role labels into backend-friendly lowercase values."""
    normalized = [
        str(role).strip().lower()
        for role in (roles or [])
        if str(role).strip()
    ]
    return normalized or ["user"]


def _has_role(current_user: Dict[str, Any], role: str) -> bool:
    """Case-insensitive role check for route authorization."""
    return any(
        str(item).strip().lower() == role.lower()
        for item in (current_user.get("roles", []) or [])
    )


def error_detail(message: str) -> Dict[str, str]:
    """Return error detail payload consistent with ErrorResponse."""
    return ErrorResponse(detail=message).model_dump()


def _serialize_user(user_data: Any) -> UserResponse:
    """Normalize auth service user objects into the public users API shape."""
    user_id = str(
        getattr(user_data, "user_id", None)
        or getattr(user_data, "id", None)
        or ""
    )
    status_value = getattr(user_data, "status", None)
    status_label = str(getattr(status_value, "value", status_value) or "").lower()
    is_active = (
        getattr(user_data, "is_active", None)
        if hasattr(user_data, "is_active")
        else status_label == "active"
    )
    created_at = getattr(user_data, "created_at", None)
    updated_at = getattr(user_data, "updated_at", None)
    last_login = getattr(user_data, "last_login", None)

    return UserResponse(
        user_id=user_id,
        email=getattr(user_data, "email", ""),
        full_name=getattr(user_data, "full_name", None),
        tenant_id=str(getattr(user_data, "tenant_id", "default") or "default"),
        roles=list(getattr(user_data, "roles", []) or []),
        preferences=getattr(user_data, "preferences", {}) or {},
        is_active=bool(is_active),
        is_verified=bool(getattr(user_data, "is_verified", True)),
        last_login=last_login.isoformat() if last_login else None,
        created_at=created_at.isoformat() if created_at else "",
        updated_at=updated_at.isoformat() if updated_at else "",
    )


error_responses = {
    400: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=201,
    responses=error_responses,
)
async def create_user(
    request: CreateUserRequest,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> UserResponse:
    """Create a new user (admin only)."""
    # Only allow admin users to create new users
    if not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403, detail=error_detail("Not authorized to create users")
        )

    try:
        auth_service = await get_auth_service_instance()
        user_data, error = await auth_service.create_user(
            email=request.email,
            password=request.password,
            full_name=request.full_name or request.email.split("@")[0],
            tenant_id=request.tenant_id,
            roles=_normalize_roles(request.roles),
        )

        if error or not user_data:
            raise HTTPException(
                status_code=400,
                detail=error_detail(error or "Failed to create user"),
            )

        return _serialize_user(user_data)

    except HTTPException:
        raise
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=error_detail(str(e)))
    except RateLimitExceededError as e:
        retry_after = (
            e.details.get("retry_after") if isinstance(e.details, dict) else None
        )
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(
            status_code=429, detail=error_detail(str(e)), headers=headers
        )
    except SecurityError as e:
        raise HTTPException(status_code=403, detail=error_detail(str(e)))
    except AuthError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(
            status_code=500, detail=error_detail("Failed to create user")
        )


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    status_code=200,
    responses=error_responses,
)
async def get_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> UserResponse:
    """Get user details (own profile or admin only)."""
    # Only allow access to own profile or for admin roles
    if current_user.get("user_id") != user_id and not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403, detail=error_detail("Not authorized to access this user")
        )

    try:
        auth_service = await get_auth_service_instance()
        user_data = await auth_service.get_user_by_id(user_id)

        if not user_data:
            raise HTTPException(status_code=404, detail=error_detail("User not found"))

        return _serialize_user(user_data)

    except UserNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("User not found"))
    except AuthError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(status_code=500, detail=error_detail("Failed to get user"))


@router.get(
    "/users/{user_id}/metrics",
    response_model=UserMetricsResponse,
    status_code=200,
    responses=error_responses,
)
async def get_user_metrics(
    user_id: str,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    analytics_service: Any = Depends(get_analytics_service),
    hours: int = 168,
) -> UserMetricsResponse:
    """Get backend-derived per-user metrics (own profile or admin only)."""
    if current_user.get("user_id") != user_id and not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail=error_detail("Not authorized to access this user's metrics"),
        )

    try:
        metrics = analytics_service.get_user_metrics(user_id, hours=hours)
        return UserMetricsResponse(**metrics)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(
            status_code=500, detail=error_detail("Failed to get user metrics")
        )


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    status_code=200,
    responses=error_responses,
)
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> UserResponse:
    """Update user details (own profile or admin only)."""
    # Only allow modifications to own profile or for admin roles
    # Admin can modify roles, regular users cannot
    if current_user.get("user_id") != user_id and not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403, detail=error_detail("Not authorized to modify this user")
        )

    # Only admin can modify roles and account status
    if (
        request.roles is not None
        or request.is_active is not None
        or request.is_verified is not None
    ) and not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403,
            detail=error_detail("Not authorized to modify user roles or status"),
        )

    try:
        auth_service = await get_auth_service_instance()

        # Get current user data
        user_data = await auth_service.get_user_by_id(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail=error_detail("User not found"))

        # Update user data using the consolidated service
        updated_user = await auth_service.update_user(
            user_id=user_id,
            full_name=request.full_name,
            roles=request.roles,
            preferences=request.preferences,
            is_active=request.is_active,
            is_verified=request.is_verified,
        )

        return _serialize_user(updated_user)

    except UserNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("User not found"))
    except SecurityError as e:
        raise HTTPException(status_code=403, detail=error_detail(str(e)))
    except AuthError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except ValueError as e:
        status_code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status_code, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(
            status_code=500, detail=error_detail("Failed to update user")
        )


@router.delete(
    "/users/{user_id}",
    status_code=204,
    responses=error_responses,
)
async def delete_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> Response:
    """Delete a user (admin only)."""
    # Only allow admin users to delete users
    if not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403, detail=error_detail("Not authorized to delete users")
        )

    # Prevent self-deletion
    if current_user.get("user_id") == user_id:
        raise HTTPException(
            status_code=400, detail=error_detail("Cannot delete your own account")
        )

    try:
        auth_service = await get_auth_service_instance()
        success = await auth_service.delete_user(user_id)

        if not success:
            raise HTTPException(status_code=404, detail=error_detail("User not found"))

        return Response(status_code=204)

    except UserNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("User not found"))
    except SecurityError as e:
        raise HTTPException(status_code=403, detail=error_detail(str(e)))
    except AuthError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(
            status_code=500, detail=error_detail("Failed to delete user")
        )


@router.get(
    "/users",
    response_model=List[UserResponse],
    status_code=200,
    responses=error_responses,
)
async def list_users(
    current_user: Dict[str, Any] = Depends(bypass_user_context_func),
    tenant_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[UserResponse]:
    """List users (admin only)."""
    # Only allow admin users to list users
    if not _has_role(current_user, "admin"):
        raise HTTPException(
            status_code=403, detail=error_detail("Not authorized to list users")
        )

    try:
        auth_service = await get_auth_service_instance()
        users = await auth_service.list_users(
            tenant_id=tenant_id if tenant_id is not None else None,
            limit=limit,
            offset=offset,
        )

        return [_serialize_user(user) for user in users]

    except AuthError as e:
        raise HTTPException(status_code=400, detail=error_detail(str(e)))
    except Exception:
        raise HTTPException(
            status_code=500, detail=error_detail("Failed to list users")
        )
