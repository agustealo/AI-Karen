from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..contracts.execution_action import ExecutionAction, ActionType

logger = logging.getLogger(__name__)


class ExtensionRuntimeAdapter:
    """Thin translation layer between AgentMedusa and the canonical extension kernel.

    This adapter does NOT:
      - discover plugins
      - authorize plugins
      - validate manifests
      - create plugin instances
      - fake results

    It only translates Medusa actions into canonical extension requests.
    """

    def __init__(self, execution_service: Optional[Any] = None):
        self.execution_service = execution_service

    async def dispatch(self, action: ExecutionAction) -> Dict[str, Any]:
        """Dispatch a Medusa extension action to the canonical execution service."""
        if action.action_type != ActionType.EXTENSION_DISPATCH:
            raise ValueError(
                f"Unsupported action type for extension adapter: {action.action_type}"
            )

        extension_id = action.payload.get("extension_id")
        method = action.payload.get("method")
        params = action.payload.get("params", {})

        if not extension_id or not method:
            return {
                "extension_id": extension_id,
                "status": "error",
                "error_code": "invalid_request",
                "result": "extension_id and method are required",
            }

        if self.execution_service is None:
            return {
                "extension_id": extension_id,
                "status": "error",
                "error_code": "unavailable",
                "result": "Extension execution service is not configured",
            }

        try:
            from ai_karen_engine.extensions.contracts import (
                ExtensionExecutionRequest,
                ExtensionExecutionContext,
            )

            context = ExtensionExecutionContext.for_runtime(
                request_id=action.execution_id or "",
                correlation_id=action.correlation_id or "",
                user_id=action.user_id or "",
                tenant_id=action.tenant_id or "default",
                session_id=action.session_id,
                conversation_id=action.conversation_id,
                roles=tuple(action.user_roles or ()),
                permissions=(),
                allowed_capabilities=tuple(action.allowed_capabilities or ()),
                policy_decision_id=action.policy_decision_id,
            )

            request = ExtensionExecutionRequest(
                plugin_id=extension_id,
                capability=method,
                payload=params,
                context=context,
                authorized_plan=action.authorized_plan,
            )

            result = await self.execution_service.execute(request)

            return {
                "extension_id": extension_id,
                "status": result.status,
                "result": result.payload,
                "source": result.source.value,
                "latency_ms": result.latency_ms,
                "error_code": result.error_code,
                "error_detail": result.error_detail,
                "side_effects": result.side_effects,
                "permission_set": result.permission_set,
                "correlation_id": result.correlation_id,
                "policy_decision_id": result.policy_decision_id,
                "execution_id": result.execution_id,
            }
        except Exception as exc:
            logger.error("Medusa extension dispatch failed: %s", exc)
            return {
                "extension_id": extension_id,
                "status": "error",
                "error_code": "dispatch_failed",
                "result": str(exc),
            }

    async def get_available_extensions(self) -> List[Dict[str, Any]]:
        """Query the canonical registry for available extensions."""
        try:
            from ai_karen_engine.extensions.registry import ExtensionRegistry

            registry = ExtensionRegistry()
            registered = registry.list_registered()
            return [
                {
                    "plugin_id": r.manifest.id,
                    "name": r.manifest.name,
                    "version": r.manifest.version,
                    "state": r.state.value,
                    "capabilities": [c.id for c in r.manifest.capabilities],
                }
                for r in registered
            ]
        except Exception as exc:
            logger.warning("Failed to list available extensions: %s", exc)
            return []
