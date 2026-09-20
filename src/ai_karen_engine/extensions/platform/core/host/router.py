"""Compatibility router that delegates to the canonical PluginService.

This module intentionally owns no loader, runner, registry, or authorization
logic.  It preserves the historical dispatch surface while forcing all plugin
execution through RuntimePolicy, ActionExecutionGate, and
ExtensionExecutionService.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.services.plugin_service import (
    ExecutionStatus,
    get_plugin_service,
)

logger = logging.getLogger("kari.plugin_router")


class PluginRouter:
    """Legacy routing surface backed by the single canonical plugin runtime."""

    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
    ) -> None:
        self.extensions_dir = extensions_dir

    async def reload(self) -> int:
        """Refresh catalog/runtime projection without eagerly importing plugins."""
        service = get_plugin_service()
        return await service.refresh_plugins()

    async def dispatch(
        self,
        intent: str,
        params: Dict[str, Any],
        roles: Optional[List[str]] = None,
        *,
        user_context: Optional[Dict[str, Any]] = None,
        authorized_plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> Any:
        """Execute a plugin intent through the canonical governed executor.

        Historical callers may still pass ``roles``.  Identity and tenant scope
        are deliberately not fabricated; callers that omit them fail closed in
        ``PluginService``.
        """
        context = dict(user_context or {})
        resolved_roles = list(context.get("roles") or roles or [])
        permissions = list(context.get("permissions") or [])
        plan = authorized_plan or context.get("authorized_plan")

        result = await get_plugin_service().execute_plugin(
            plugin_name=intent,
            parameters=dict(params or {}),
            timeout_seconds=int(context.get("timeout_seconds") or 30),
            user_id=context.get("user_id"),
            tenant_id=context.get("tenant_id"),
            session_id=context.get("session_id"),
            conversation_id=context.get("conversation_id"),
            correlation_id=context.get("correlation_id"),
            roles=resolved_roles,
            permissions=permissions,
            policy_decision_id=context.get("policy_decision_id"),
            authorized_plan=plan,
            allowed_capabilities=list(context.get("allowed_capabilities") or []),
            forbidden_capabilities=list(
                context.get("forbidden_capabilities") or []
            ),
        )

        if result.status is ExecutionStatus.COMPLETED:
            return result.result

        message = result.error or "Plugin execution failed"
        permission_errors = {
            "permission_denied",
            "permission_plan_mismatch",
            "plugin_not_authorized",
            "action_gate_denied",
            "policy_denied",
            "authorized_scope_mismatch",
            "authorized_plan_required",
            "authorized_plan_invalid",
        }
        if result.error_code in permission_errors:
            raise PermissionError(message)
        raise RuntimeError(
            f"{result.error_code or 'plugin_execution_failed'}: {message}"
        )

    def get_api_router(self) -> Any:
        """Return an empty compatibility router.

        Plugin-owned FastAPI routers are no longer imported and mounted directly,
        because doing so bypasses the governed execution boundary.  Plugin HTTP
        ingress must use the canonical plugin API routes.
        """
        from fastapi import APIRouter

        return APIRouter()


_router_instance: Optional[PluginRouter] = None


def get_plugin_router() -> PluginRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = PluginRouter()
    return _router_instance
