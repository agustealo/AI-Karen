"""Compatibility router backed by the canonical plugin service.

The historical platform router used its own loader, registry and runner. That
created a second execution authority capable of bypassing RuntimePolicy,
AuthorizedExecutionPlan, ActionExecutionGate, tenant binding and the canonical
executor. This adapter keeps the old symbol available while delegating all
runtime work to ``PluginService``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.plugin_service import ExecutionStatus, get_plugin_service

logger = logging.getLogger("kari.plugin_router")


class PluginRouter:
    """Deprecated compatibility adapter over the canonical plugin runtime."""

    def __init__(self, extensions_dir: str = "src/ai_karen_engine/extensions/plugins"):
        self.extensions_dir = extensions_dir

    async def reload(self) -> int:
        """Refresh the canonical catalog/runtime projection without importing plugins."""
        service = get_plugin_service()
        if not service.initialized:
            await service.initialize(auto_discover=True)
            stats = service.get_service_stats().get("registry_stats", {})
            return int(stats.get("total_plugins", 0) or 0)
        return await service.refresh_plugins()

    async def dispatch(
        self,
        intent: str,
        params: Dict[str, Any],
        roles: Optional[List[str]] = None,
        *,
        user_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute through ``PluginService`` or fail closed without identity scope.

        Older callers supplied only role names. Roles alone are not sufficient
        authorization, so those calls now fail instead of silently bypassing the
        canonical policy and tenant gates.
        """
        context = dict(user_context or {})
        service = get_plugin_service()
        result = await service.execute_plugin(
            intent,
            parameters=dict(params or {}),
            user_id=str(context.get("user_id") or "").strip() or None,
            tenant_id=str(context.get("tenant_id") or "").strip() or None,
            session_id=context.get("session_id"),
            conversation_id=context.get("conversation_id"),
            correlation_id=context.get("correlation_id"),
            roles=list(context.get("roles") or roles or []),
            permissions=list(context.get("permissions") or []),
            policy_decision_id=context.get("policy_decision_id"),
            authorized_plan=context.get("authorized_plan"),
            allowed_capabilities=list(context.get("allowed_capabilities") or []),
            forbidden_capabilities=list(context.get("forbidden_capabilities") or []),
        )
        if result.status is not ExecutionStatus.COMPLETED:
            raise PermissionError(
                result.error or result.error_code or "Canonical plugin execution denied"
            )
        return result.result

    def get_api_router(self) -> Any:
        """Reject runtime API mounting from imported plugin instances.

        Dynamic API materialization from live instances was part of the retired
        execution path. Platform/API routes must be built from catalog metadata
        or explicit governed services instead.
        """
        raise RuntimeError(
            "PluginRouter no longer mounts APIs from live plugin instances; "
            "use catalog-backed platform API routes"
        )


_router_instance: Optional[PluginRouter] = None


def get_plugin_router() -> PluginRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = PluginRouter()
    return _router_instance
