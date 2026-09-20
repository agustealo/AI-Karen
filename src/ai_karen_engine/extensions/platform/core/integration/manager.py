"""Compatibility integration manager over the canonical plugin runtime.

This module no longer owns an independent permissions manager, sandbox, router,
or lifecycle executor. Historical callers are preserved, but execution always
flows through PluginService -> RuntimePolicy -> ActionExecutionGate ->
ExtensionExecutionService.

PluginService is resolved lazily so platform package imports never create a
PluginKernel -> platform -> PluginService -> PluginKernel cycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ai_karen_engine.services.plugin_service import PluginService

logger = logging.getLogger("kari.plugin_manager")


def get_plugin_service() -> "PluginService":
    from ai_karen_engine.services.plugin_service import get_plugin_service as _get

    return _get()


@dataclass
class ExtensionExecutionResult:
    extension_id: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class PluginManager:
    """Legacy application surface backed entirely by PluginService."""

    def __init__(
        self, extensions_dir: str = "src/ai_karen_engine/extensions/plugins"
    ) -> None:
        self.extensions_dir = extensions_dir

    async def initialize(self) -> None:
        service = get_plugin_service()
        if not service.initialized:
            await service.initialize(auto_discover=True)
        logger.info("Canonical plugin runtime ready")

    async def run_plugin(
        self, name: str, params: Dict[str, Any], user_ctx: Dict[str, Any]
    ) -> Any:
        """Execute through the canonical governed plugin service."""
        from ai_karen_engine.services.plugin_service import ExecutionStatus

        context = dict(user_ctx or {})
        result = await get_plugin_service().execute_plugin(
            plugin_name=name,
            parameters=dict(params or {}),
            timeout_seconds=int(context.get("timeout_seconds") or 30),
            user_id=context.get("user_id"),
            tenant_id=context.get("tenant_id"),
            session_id=context.get("session_id"),
            conversation_id=context.get("conversation_id"),
            correlation_id=context.get("correlation_id"),
            roles=list(context.get("roles") or []),
            permissions=list(context.get("permissions") or []),
            policy_decision_id=context.get("policy_decision_id"),
            authorized_plan=context.get("authorized_plan"),
            allowed_capabilities=list(context.get("allowed_capabilities") or []),
            forbidden_capabilities=list(
                context.get("forbidden_capabilities") or []
            ),
        )
        if result.status is ExecutionStatus.COMPLETED:
            return result.result

        message = result.error or "Plugin execution failed"
        if result.error_code in {
            "permission_denied",
            "permission_plan_mismatch",
            "plugin_not_authorized",
            "action_gate_denied",
            "policy_denied",
            "authorized_scope_mismatch",
            "authorized_plan_required",
            "authorized_plan_invalid",
        }:
            raise PermissionError(message)
        raise RuntimeError(
            f"{result.error_code or 'plugin_execution_failed'}: {message}"
        )

    async def dispatch_agent_action(self, agent_action: Any, context: Any):
        """Dispatch an agent action through the canonical plugin service."""
        start_time = time.time()
        extension_id = agent_action.extension_id or agent_action.tool

        if not extension_id:
            return ExtensionExecutionResult(
                extension_id="unknown",
                success=False,
                error="No extension_id or tool specified in agent action",
                execution_time_ms=0,
            )

        user_ctx = {
            "roles": list(getattr(context, "user_roles", []) or []),
            "permissions": list(getattr(context, "permissions", []) or []),
            "user_id": getattr(context, "user_id", None),
            "tenant_id": getattr(context, "tenant_id", None),
            "session_id": getattr(context, "session_id", None),
            "conversation_id": getattr(context, "conversation_id", None),
            "correlation_id": getattr(context, "correlation_id", None),
            "policy_decision_id": getattr(context, "policy_decision_id", None),
            "authorized_plan": getattr(context, "authorized_plan", None),
            "allowed_capabilities": list(
                getattr(context, "allowed_capabilities", []) or []
            ),
            "forbidden_capabilities": list(
                getattr(context, "forbidden_capabilities", []) or []
            ),
        }

        try:
            result = await self.run_plugin(
                name=extension_id,
                params=dict(agent_action.params or {}),
                user_ctx=user_ctx,
            )
            elapsed = int((time.time() - start_time) * 1000)
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=True,
                data={"result": result} if not isinstance(result, dict) else result,
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.time() - start_time) * 1000)
            logger.warning(
                "Extension execution failed for %s: %s",
                extension_id,
                exc,
            )
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=False,
                error=str(exc),
                execution_time_ms=elapsed,
            )

    def get_health_summary(self) -> Dict[str, Any]:
        service = get_plugin_service()
        stats = service.get_service_stats()
        if not stats.get("initialized"):
            return {
                "status": "initializing",
                "active_count": 0,
                "discovered_count": 0,
                "lifecycle_states": {},
                "authority": "PluginService",
            }
        registry = stats.get("registry_stats", {})
        by_status = registry.get("by_status", {})
        active_count = sum(
            int(by_status.get(state, 0) or 0)
            for state in ("registered", "enabled", "loaded", "active")
        )
        return {
            "status": "healthy",
            "active_count": active_count,
            "discovered_count": int(registry.get("total_plugins", 0) or 0),
            "lifecycle_states": dict(by_status),
            "authority": "PluginService",
        }


_manager_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PluginManager()
    return _manager_instance
