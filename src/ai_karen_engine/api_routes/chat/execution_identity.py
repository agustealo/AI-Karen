"""Trusted chat execution identity helpers.

Transport adapters may validate and translate requests, but they must never
invent authenticated user or tenant scope. This module centralizes the small
amount of identity adaptation required by HTTP, Copilot, SSE, and WebSocket
chat surfaces before delegating execution to :class:`ChatRuntime`.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

_SYNTHETIC_TENANT_IDS = frozenset({"default", "dev-tenant"})


def require_execution_identity(user: Mapping[str, Any]) -> tuple[str, str]:
    """Return authoritative ``(user_id, tenant_id)`` or fail closed.

    Authentication middleware owns identity construction. Chat transports only
    verify that the resulting scope is explicit enough to enter the runtime.
    Synthetic tenant identifiers are deliberately rejected here because memory
    recall and persistence require tenant isolation to be authoritative.
    """

    user_id = str(user.get("user_id") or "").strip()
    tenant_id = str(user.get("tenant_id") or "").strip()

    if not user_id or user_id == "anonymous":
        raise HTTPException(
            status_code=401,
            detail="Authenticated user identity is required",
        )
    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Authenticated tenant context is required",
        )
    if tenant_id.lower() in _SYNTHETIC_TENANT_IDS:
        raise HTTPException(
            status_code=401,
            detail="Authenticated tenant context is not authoritative",
        )

    return user_id, tenant_id


def build_chat_execution_context(
    *,
    user: Mapping[str, Any],
    session_id: str,
    conversation_id: str,
    request_id: str,
    correlation_id: str,
) -> ChatExecutionContext:
    """Build the canonical runtime context from trusted server-owned identity."""

    user_id, tenant_id = require_execution_identity(user)
    return ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id=correlation_id,
        roles=list(user.get("roles") or []),
        permissions=list(user.get("permissions") or user.get("scopes") or []),
    )


def can_execute_copilot_action(user: Mapping[str, Any]) -> bool:
    """Return whether the authenticated principal may execute Copilot actions."""

    roles = {str(role).strip().lower() for role in (user.get("roles") or [])}
    permissions = {
        str(permission).strip().lower()
        for permission in (user.get("permissions") or user.get("scopes") or [])
    }
    return bool(
        "admin" in roles
        or "copilot:execute" in permissions
        or "chat:write" in permissions
    )


__all__ = [
    "build_chat_execution_context",
    "can_execute_copilot_action",
    "require_execution_identity",
]
