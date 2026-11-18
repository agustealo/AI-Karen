"""Session helpers bridging to the production authentication service."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from functools import lru_cache
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_karen_engine.core.security.auth_config import (
    DevelopmentIdentityConfigurationError,
    auth_config,
)

from .models import UserData

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _get_auth_middleware():
    """Resolve the production authentication middleware."""
    from ai_karen_engine.auth.auth_middleware import get_auth_middleware

    return get_auth_middleware()


async def _authenticate_request(request: Request) -> Dict[str, Any]:
    if auth_config.should_bypass_auth():
        logger.debug("Auth bypass active in session helper")
        try:
            return auth_config.get_dev_user_context()
        except DevelopmentIdentityConfigurationError as exc:
            logger.error("auth.session.dev_identity_unconfigured")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    middleware = _get_auth_middleware()
    user_data = await middleware.authenticate_request(request)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user_data


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserData:
    """Resolve an authenticated user with explicit tenant scope."""
    del credentials
    payload = await _authenticate_request(request)
    user = UserData.ensure(payload)
    tenant_id = str(user.tenant_id or "").strip()
    if not tenant_id or tenant_id == "default":
        logger.error(
            "auth.session.invalid_tenant_scope",
            extra={"user_id": user.user_id, "tenant_id": tenant_id or None},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explicit tenant scope is required",
        )
    return user


async def get_plugin_lifecycle_context(request: Request):
    """Resolve a current, bearer-bound, high-risk plugin management context.

    Only the canonical authentication middleware may validate the access
    token and its backed active session. The verified token ID, not a client
    session/conversation field or legacy synthetic identity, becomes the
    immutable lifecycle session scope. Cookie-only requests and configured
    developer auth bypass cannot create physical-mutation authority.
    """
    from ai_karen_engine.auth.auth_middleware import TokenStatus
    from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

    if auth_config.should_bypass_auth():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verified production authentication is required for plugin lifecycle",
        )

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified bearer session required for plugin lifecycle",
        )
    token = authorization.removeprefix("Bearer ")
    if not token or token.strip() != token or any(ch.isspace() for ch in token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer session",
        )
    middleware = _get_auth_middleware()
    verified = await middleware.validate_token(token)
    if not isinstance(verified, dict) or verified.get("status") is not TokenStatus.VALID:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if isinstance(verified, dict) and verified.get("http_status") == 503
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(
            status_code=response_status,
            detail="Active authenticated session could not be verified",
        )

    payload = verified.get("payload")
    if not isinstance(payload, dict) or payload.get("type") == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified access session is required",
        )
    token_id = payload.get("token_id")
    if (
        not isinstance(token_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", token_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated session identity is incomplete",
        )
    principal = UserData.from_dict(middleware._get_user_from_payload(payload))
    if not principal.is_active or not principal.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated principal is inactive",
        )
    try:
        actor = str(uuid.UUID(str(principal.user_id)))
        tenant = str(uuid.UUID(str(principal.tenant_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Canonical plugin lifecycle identity is required",
        ) from exc
    if actor != principal.user_id or tenant != principal.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Canonical plugin lifecycle identity is required",
        )
    rbac = get_rbac_manager()
    granted = rbac.has_permission(principal, Permission.ADMIN_PLUGINS_MANAGE)
    rbac.audit_access_attempt(
        principal,
        Permission.ADMIN_PLUGINS_MANAGE,
        resource=request.url.path,
        granted=granted,
        request=request,
        additional_context={"action": "manage_plugin_lifecycle"},
    )
    if not granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Plugin lifecycle management permission required",
        )

    def trace_id(value: object) -> str:
        if (
            isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)
        ):
            return value
        return str(uuid.uuid4())

    # Keep the signed token identifier out of audit events and durable
    # approval rows. High-entropy token IDs remain uniquely bound to this
    # user/tenant/session through a one-way deterministic digest.
    scoped_session_id = hashlib.sha256(
        f"ai-karen:plugin-lifecycle:{tenant}:{actor}:{token_id}".encode("utf-8")
    ).hexdigest()
    return ChatExecutionContext(
        user_id=actor,
        tenant_id=tenant,
        session_id=scoped_session_id,
        request_id=trace_id(
            getattr(request.state, "request_id", None)
            or request.headers.get("X-Request-Id")
        ),
        correlation_id=trace_id(
            getattr(request.state, "correlation_id", None)
            or request.headers.get("X-Correlation-Id")
        ),
        roles=list(principal.roles or []),
        permissions=list(principal.permissions or []),
        authenticated_user=principal,
    )


__all__ = ["get_current_user", "get_plugin_lifecycle_context"]
