"""Session helpers bridging to the production authentication service."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import UserData

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _get_auth_middleware():
    """Resolve the production authentication middleware."""
    from ai_karen_engine.auth.auth_middleware import get_auth_middleware

    return get_auth_middleware()


def _configured_dev_tenant_id() -> str:
    """Return explicit development tenant scope or fail closed."""
    tenant_id = str(os.getenv("KAREN_DEV_TENANT_ID") or "").strip()
    if not tenant_id or tenant_id == "default":
        raise RuntimeError(
            "Auth bypass requires explicit KAREN_DEV_TENANT_ID; 'default' is forbidden"
        )
    return tenant_id


async def _authenticate_request(request: Request) -> Dict[str, Any]:
    from ai_karen_engine.core.security.auth_config import auth_config

    if auth_config.should_bypass_auth():
        logger.debug("Auth bypass active in session helper")
        return {
            "user_id": "dev-user",
            "tenant_id": _configured_dev_tenant_id(),
            "email": "dev-user@localhost",
            "user_type": "developer",
            "roles": ["admin", "user"],
            "permissions": [
                "extension:*",
                "chat:*",
                "admin:*",
                "agent:*",
                "tasks:*",
                "scheduler:*",
            ],
            "token_id": "dev-token-id",
        }

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


__all__ = ["get_current_user"]
