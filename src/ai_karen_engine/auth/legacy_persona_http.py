"""Fail-closed historical persona migration HTTP authentication adapter.

Read-only inspection; the canonical runtime and NeuroVault govern execution.
"""
from __future__ import annotations

async def migration_policy_request_from_authenticated_http(
    *, request: "Request", request_id: str, correlation_id: str,
) -> "PolicyEvaluationRequest":
    """Fail-closed HTTP credential boundary; read-only, no migration execution.

    Authenticate directly through the existing middleware instead of trusting
    request.state.user or a caller-constructed ChatExecutionContext. Historical
    operations require functioning revocation storage, even if ordinary chat
    tolerates a degraded auth revocation backend.
    """
    from fastapi import Request
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.auth.auth_middleware import (
        AuthenticationError, get_auth_middleware,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

    if not isinstance(request, Request):
        raise TypeError("canonical HTTP request required")
    if auth_config.should_bypass_auth():
        raise PermissionError("historical migration forbidden with auth bypass")
    middleware = get_auth_middleware()
    store = middleware.redis_client
    if store is None:
        raise PermissionError("historical migration requires revocation store")
    try:
        # Redis may report failure as a false result rather than raising.
        # A missing revocation guarantee must never authorize inspection.
        if store.ping() is not True:
            raise PermissionError("historical migration revocation store unavailable")
        token = middleware._extract_token_from_request(request)
        if not token:
            raise PermissionError("historical migration requires access token")
        payload = middleware._decode_jwt(token)
        token_id = str(payload.get("token_id") or "").strip()
        if not token_id:
            raise PermissionError("historical migration token invalid or revoked")
        # Check the revocation store directly because the generic middleware
        # intentionally degrades to not-revoked when its lookup fails.
        revoked = store.exists(middleware._get_redis_key("revoked", token_id))
        # Redis EXISTS returns an integer. None or an unexpected value must
        # not be interpreted as proof of a valid, non-revoked session.
        if type(revoked) is not int or revoked < 0:
            raise PermissionError("historical migration revocation lookup unavailable")
        if revoked != 0:
            raise PermissionError("historical migration token revoked")
        principal = middleware._get_user_from_payload(payload)
        permissions = principal.get("permissions")
        roles = principal.get("roles")
        if (
            not isinstance(permissions, list)
            or not all(isinstance(item, str) for item in permissions)
            or not isinstance(roles, list)
            or not all(isinstance(item, str) for item in roles)
        ):
            raise PermissionError("historical migration credential claims invalid")
        if "memory.write" not in permissions:
            raise PermissionError("historical migration write permission required")
        if not request_id or not request_id.strip() or not correlation_id or not correlation_id.strip():
            raise ValueError("request and correlation identity required")
        context = ChatExecutionContext(
            tenant_id=principal["tenant_id"], user_id=principal["user_id"],
            session_id=token_id, request_id=request_id,
            correlation_id=correlation_id,
            roles=list(principal.get("roles") or []),
            permissions=list(principal.get("permissions") or []),
        )
        from ai_karen_engine.core.memory.legacy_persona_admission import migration_policy_request_from_runtime_context
        return migration_policy_request_from_runtime_context(context=context)
    except (PermissionError, ValueError, TypeError):
        raise
    except AuthenticationError as exc:
        raise PermissionError("historical migration authentication failed") from exc
    except Exception as exc:
        raise PermissionError("historical migration credential verification unavailable") from exc


