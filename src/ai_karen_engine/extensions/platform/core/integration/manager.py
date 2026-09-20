"""Platform workflow adapter for the canonical plugin runtime.

This module intentionally owns no discovery, permission, routing, loading, or
execution authority. Workflow callers may keep using ``PluginManager`` while all
plugin execution is delegated to ``PluginService`` and therefore reaches the
canonical ``PluginKernel`` / ``ExtensionExecutionService`` path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ai_karen_engine.services.plugin_service import (
    ExecutionStatus,
    PluginService,
    get_plugin_service,
)

logger = logging.getLogger("kari.plugin_manager")


@dataclass
class ExtensionExecutionResult:
    """Compatibility result used by agent-action integration callers."""

    extension_id: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class PluginManager:
    """Thin workflow/agent adapter over the canonical ``PluginService``."""

    def __init__(self, extensions_dir: str = "src/ai_karen_engine/extensions/plugins"):
        self.extensions_dir = extensions_dir
        self._service: Optional[PluginService] = None

    def _plugin_service(self) -> PluginService:
        service = get_plugin_service()
        self._service = service
        return service

    async def initialize(self) -> None:
        """Ensure the one canonical plugin service is initialized."""
        service = self._plugin_service()
        if not service.initialized:
            await service.initialize(auto_discover=True)
        logger.info("Platform integration attached to canonical plugin runtime")

    async def run_plugin(
        self, name: str, params: Dict[str, Any], user_ctx: Dict[str, Any]
    ) -> Any:
        """Execute a workflow plugin through the canonical governed runtime.

        Identity and tenant scope are deliberately fail-closed. Permission and
        policy decisions are not reimplemented here; they are passed to
        ``PluginService`` so RuntimePolicy, ``AuthorizedExecutionPlan`` and
        ``ActionExecutionGate`` remain authoritative.
        """
        service = self._plugin_service()
        result = await service.execute_plugin(
            name,
            parameters=dict(params or {}),
            user_id=str(user_ctx.get("user_id") or "").strip() or None,
            tenant_id=str(user_ctx.get("tenant_id") or "").strip() or None,
            session_id=user_ctx.get("session_id"),
            conversation_id=user_ctx.get("conversation_id"),
            correlation_id=user_ctx.get("correlation_id"),
            roles=list(user_ctx.get("roles") or []),
            permissions=list(user_ctx.get("permissions") or []),
            policy_decision_id=user_ctx.get("policy_decision_id"),
            authorized_plan=user_ctx.get("authorized_plan"),
            allowed_capabilities=list(user_ctx.get("allowed_capabilities") or []),
            forbidden_capabilities=list(user_ctx.get("forbidden_capabilities") or []),
        )
        if result.status is not ExecutionStatus.COMPLETED:
            message = result.error or result.error_code or "Plugin execution failed"
            authorization_errors = {
                "identity_scope_missing",
                "principal_permission_missing",
                "policy_denied",
                "authorized_plan_missing",
                "authorized_scope_mismatch",
                "plugin_not_authorized",
                "permission_plan_mismatch",
                "action_gate_denied",
            }
            if result.error_code in authorization_errors:
                raise PermissionError(message)
            raise RuntimeError(message)
        return result.result

    async def dispatch_agent_action(self, agent_action: Any, context: Any):
        """Execute an AgentAction through the same canonical plugin authority."""
        start_time = time.monotonic()
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
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=True,
                data={"result": result} if not isinstance(result, dict) else result,
                execution_time_ms=duration_ms,
            )
        except (PermissionError, RuntimeError) as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "Canonical extension execution rejected for %s: %s",
                extension_id,
                exc,
            )
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=False,
                error=str(exc),
                execution_time_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception("Canonical extension execution failed for %s", extension_id)
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=False,
                error=str(exc),
                execution_time_ms=duration_ms,
            )

    def get_health_summary(self) -> Dict[str, Any]:
        """Project health from the canonical plugin service only."""
        service = self._plugin_service()
        stats = service.get_service_stats()
        if not stats.get("initialized"):
            return {
                "status": "not_initialized",
                "authority": "PluginService",
                "discovered_count": 0,
                "active_count": 0,
            }
        registry = stats.get("registry_stats", {})
        status_counts = registry.get("by_status", {})
        enabled_states = {"registered", "enabled", "loaded", "active"}
        return {
            "status": "healthy",
            "authority": "PluginService",
            "discovered_count": int(registry.get("total_plugins", 0) or 0),
            "active_count": sum(
                int(status_counts.get(state, 0) or 0) for state in enabled_states
            ),
            "lifecycle_states": dict(status_counts),
        }


_manager_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PluginManager()
    return _manager_instance
