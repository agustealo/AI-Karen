from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


def serialize_user_account(user: Any) -> Optional[Dict[str, Any]]:
    """Normalize user objects for legacy callers without performing auth."""
    if user is None:
        return None
    if isinstance(user, dict):
        return user
    if hasattr(user, "__dict__"):
        return {
            key: value
            for key, value in vars(user).items()
            if not key.startswith("_")
        }
    return None


def derive_permissions(user_profile: Dict[str, Any]) -> Dict[str, bool]:
    """Legacy metadata helper.

    RuntimePolicy owns authorization. These values are descriptive compatibility
    metadata only and must never be used by graph nodes as an execution gate.
    """
    roles = {str(role).lower() for role in user_profile.get("roles", [])}
    is_active = bool(user_profile.get("is_active", True))

    return {
        "chat": is_active,
        "tools": bool(roles.intersection({"admin", "developer", "power_user"})),
        "model_management": "admin" in roles,
        "analytics": bool(roles.intersection({"admin", "analyst"})),
    }


class AuthGateNode:
    """Validate the trusted Runtime identity carried into a workflow.

    Authentication and tenant resolution happen before ChatRuntime enters
    WorkflowRuntime. LangGraph is deliberately not an authentication authority:
    it does not validate tokens, fetch users, synthesize fallback identities, or
    invent tenant scope. RuntimePolicy remains the sole authorization authority.
    """

    def __init__(self, auth_service: Any = None):
        # Retain the constructor argument for compatibility with callers while
        # intentionally refusing to use it as a second authentication path.
        self._auth_service = auth_service

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        errors = state.setdefault("errors", [])
        auth_context = state.get("auth_context")

        if not isinstance(auth_context, dict):
            state["auth_status"] = "failed"
            errors.append("Trusted Runtime authentication context is required")
            return state

        trusted_user_id = str(auth_context.get("user_id") or "").strip()
        trusted_tenant_id = str(auth_context.get("tenant_id") or "").strip()
        state_user_id = str(state.get("user_id") or "").strip()
        state_tenant_id = str(state.get("tenant_id") or "").strip()

        if not trusted_user_id or not trusted_tenant_id:
            state["auth_status"] = "failed"
            errors.append("Trusted Runtime identity is incomplete")
            return state

        if state_user_id and state_user_id != trusted_user_id:
            logger.warning(
                "langgraph.runtime_identity_mismatch",
                extra={"correlation_id": state.get("correlation_id")},
            )
            state["auth_status"] = "failed"
            errors.append("Runtime user identity mismatch")
            return state

        if state_tenant_id and state_tenant_id != trusted_tenant_id:
            logger.warning(
                "langgraph.runtime_tenant_mismatch",
                extra={"correlation_id": state.get("correlation_id")},
            )
            state["auth_status"] = "failed"
            errors.append("Runtime tenant identity mismatch")
            return state

        roles = [str(role) for role in auth_context.get("roles", [])]
        permissions = [
            str(permission) for permission in auth_context.get("permissions", [])
        ]
        state["user_id"] = trusted_user_id
        state["tenant_id"] = trusted_tenant_id
        state["user_profile"] = {
            "user_id": trusted_user_id,
            "tenant_id": trusted_tenant_id,
            "roles": roles,
            "permissions": permissions,
            "is_active": True,
            "source": "runtime_auth_context",
        }
        state["user_permissions"] = derive_permissions(state["user_profile"])
        state["auth_status"] = "authenticated"

        logger.info(
            "langgraph.runtime_identity_validated",
            extra={
                "correlation_id": state.get("correlation_id"),
                "user_id": trusted_user_id,
                "tenant_id": trusted_tenant_id,
            },
        )
        return state


async def auth_gate_node(
    state: LangGraphOrchestrationState,
    auth_service: Any = None,
) -> LangGraphOrchestrationState:
    """Compatibility wrapper for the Runtime identity validation node."""
    node = AuthGateNode(auth_service)
    return await node(state)
