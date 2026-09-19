"""Application facade for the canonical plugin kernel.

PluginService preserves the HTTP/application contract while delegating catalog
truth to the extension platform registry and execution to
ExtensionExecutionService through PluginKernel.  It is not an execution or
discovery authority.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.core.runtime.policy import PolicyEvaluationRequest, RuntimePolicyEnforcer
from ai_karen_engine.extensions.contracts import (
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel

logger = logging.getLogger(__name__)
_ENABLED_STATES = {"registered", "enabled", "loaded", "active"}
_CANONICAL_PLUGIN_ROOT = Path("src/ai_karen_engine/extensions/plugins")


class ExecutionMode(str, Enum):
    """Compatibility hint retained at the application boundary.

    Isolation is governed by the runtime manifest and canonical executor; this
    value no longer selects a second execution engine.
    """

    DIRECT = "direct"
    THREAD = "thread"
    PROCESS = "process"
    SANDBOX = "sandbox"


class ExecutionStatus(str, Enum):
    """Stable application-facing execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PluginExecutionResult:
    """HTTP/application view of a canonical ExtensionExecutionResult."""

    request_id: str
    plugin_name: str
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    plugin_id: str = ""
    plugin_version: str = ""
    user_id: str = ""
    tenant_id: str = ""
    session_id: str = ""
    conversation_id: str = ""
    correlation_id: str = ""
    policy_decision_id: str = ""
    requested_capabilities: List[str] = field(default_factory=list)
    granted_capabilities: List[str] = field(default_factory=list)
    error_code: Optional[str] = None


class PluginService:
    """Thin application facade over the canonical plugin kernel."""

    def __init__(
        self,
        marketplace_path: Optional[Path] = None,
        core_plugins_path: Optional[Path] = None,
    ) -> None:
        self.marketplace_path = marketplace_path
        self.core_plugins_path = core_plugins_path
        self.kernel: Optional[PluginKernel] = None
        self.initialized = False
        self._policy_enforcer = RuntimePolicyEnforcer()
        self._history: List[PluginExecutionResult] = []

    def _resolve_root(self) -> Path:
        marketplace = Path(self.marketplace_path) if self.marketplace_path else None
        core = Path(self.core_plugins_path) if self.core_plugins_path else None
        if marketplace is not None and core is not None:
            if marketplace.resolve() != core.resolve():
                raise ValueError(
                    "PluginService requires one canonical plugin root; "
                    "marketplace_path and core_plugins_path must resolve to the same path"
                )
        return core or marketplace or _CANONICAL_PLUGIN_ROOT

    async def initialize(self, auto_discover: bool = True) -> None:
        if self.initialized and self.kernel is not None:
            return
        root = self._resolve_root()
        self.kernel = PluginKernel(root)
        await self.kernel.initialize(auto_discover=auto_discover)
        self.initialized = True

    async def _ensure_initialized(self) -> None:
        if not self.initialized or self.kernel is None:
            await self.initialize()

    def _get_kernel(self) -> PluginKernel:
        if self.kernel is None:
            raise RuntimeError("Plugin kernel is not initialized")
        return self.kernel

    async def discover_plugins(
        self, force_refresh: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        await self._ensure_initialized()
        kernel = self._get_kernel()
        if force_refresh:
            await kernel.refresh()
        return {
            str(record["manifest"].name): record
            for record in kernel.list_records()
        }

    async def validate_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        record = self._get_kernel().get_record(plugin_name)
        return bool(record and not record.get("error_message"))

    async def register_plugin(self, plugin_name: str) -> bool:
        """Compatibility operation: valid discovered plugins are projected automatically."""
        await self._ensure_initialized()
        return self._get_kernel().runtime_registry.get(plugin_name) is not None

    async def validate_and_register_plugin(self, plugin_name: str) -> bool:
        return await self.validate_plugin(plugin_name) and await self.register_plugin(
            plugin_name
        )

    async def validate_and_register_all_discovered(self) -> Dict[str, bool]:
        await self._ensure_initialized()
        return {
            str(record["manifest"].name): not bool(record.get("error_message"))
            and self._get_kernel().runtime_registry.get(
                str(record["manifest"].name)
            )
            is not None
            for record in self._get_kernel().list_records()
        }

    async def refresh_plugins(self) -> int:
        await self._ensure_initialized()
        return await self._get_kernel().refresh()

    @staticmethod
    def _type_matches(value: Any, expected: str) -> bool:
        mapping = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
            "null": lambda item: item is None,
        }
        validator = mapping.get(str(expected).lower())
        if validator is None:
            raise ValueError(f"Unsupported schema type '{expected}'")
        return bool(validator(value))

    @classmethod
    def _validate_value(
        cls, value: Any, rules: Dict[str, Any], path: str
    ) -> None:
        expected = rules.get("type")
        if expected and not cls._type_matches(value, str(expected)):
            raise ValueError(f"Parameter '{path}' must be of type '{expected}'")
        allowed = rules.get("enum")
        if allowed is not None and value not in allowed:
            raise ValueError(f"Parameter '{path}' is not an allowed value")

        if isinstance(value, str):
            minimum = rules.get("minLength", rules.get("min_length"))
            maximum = rules.get("maxLength", rules.get("max_length"))
            if minimum is not None and len(value) < int(minimum):
                raise ValueError(f"Parameter '{path}' is too short")
            if maximum is not None and len(value) > int(maximum):
                raise ValueError(f"Parameter '{path}' is too long")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = rules.get("minimum", rules.get("min"))
            maximum = rules.get("maximum", rules.get("max"))
            if minimum is not None and value < minimum:
                raise ValueError(f"Parameter '{path}' is below minimum")
            if maximum is not None and value > maximum:
                raise ValueError(f"Parameter '{path}' exceeds maximum")

        if isinstance(value, list) and isinstance(rules.get("items"), dict):
            for index, item in enumerate(value):
                cls._validate_value(item, rules["items"], f"{path}[{index}]")

        if isinstance(value, dict) and isinstance(rules.get("properties"), dict):
            properties = rules["properties"]
            required = {str(item) for item in rules.get("required", []) or []}
            missing = sorted(required - set(value))
            if missing:
                raise ValueError(
                    f"Parameter '{path}' is missing required fields: {', '.join(missing)}"
                )
            additional = rules.get(
                "additionalProperties",
                rules.get("additional_properties", True),
            )
            unexpected = set(value) - set(properties)
            if unexpected and not bool(additional):
                raise ValueError(
                    f"Parameter '{path}' contains undeclared fields: "
                    + ", ".join(sorted(unexpected))
                )
            for key, nested in value.items():
                nested_rules = properties.get(key)
                if isinstance(nested_rules, dict):
                    cls._validate_value(nested, nested_rules, f"{path}.{key}")

    def _validate_parameter_contract(
        self, plugin_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(parameters, dict):
            raise ValueError("Plugin parameters must be a JSON object")
        record = self._get_kernel().get_record(plugin_name)
        if record is None:
            raise LookupError(plugin_name)
        manifest = record.get("manifest")
        schema = getattr(manifest, "config_schema", None)
        if schema is None:
            return dict(parameters)
        schema_data = (
            schema.model_dump()
            if hasattr(schema, "model_dump")
            else dict(schema)
            if isinstance(schema, dict)
            else {}
        )
        if not schema_data:
            return dict(parameters)
        rules = {
            "type": schema_data.get("type", "object"),
            "properties": schema_data.get("properties", {}),
            "required": schema_data.get("required", []),
            "additionalProperties": schema_data.get(
                "additional_properties",
                schema_data.get("additionalProperties", True),
            ),
        }
        self._validate_value(parameters, rules, "parameters")
        return dict(parameters)

    async def validate_plugin_parameters(
        self, plugin_name: str, parameters: Dict[str, Any]
    ) -> bool:
        await self._ensure_initialized()
        try:
            self._validate_parameter_contract(plugin_name, parameters)
        except (LookupError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _failure(
        *,
        request_id: str,
        plugin_name: str,
        code: str,
        message: str,
        user_id: str,
        tenant_id: str,
        session_id: Optional[str],
        conversation_id: Optional[str],
        correlation_id: str,
        policy_decision_id: Optional[str],
        requested_capabilities: List[str],
    ) -> PluginExecutionResult:
        now = datetime.now(timezone.utc)
        return PluginExecutionResult(
            request_id=request_id,
            plugin_name=plugin_name,
            plugin_id=plugin_name,
            status=ExecutionStatus.FAILED,
            error=message,
            error_code=code,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=str(session_id or ""),
            conversation_id=str(conversation_id or ""),
            correlation_id=correlation_id,
            policy_decision_id=str(policy_decision_id or ""),
            requested_capabilities=list(requested_capabilities),
            completed_at=now,
        )

    @staticmethod
    def _adapt_result(
        result: ExtensionExecutionResult,
        *,
        plugin_name: str,
        user_id: str,
        tenant_id: str,
        session_id: Optional[str],
        conversation_id: Optional[str],
        requested_capabilities: List[str],
        granted_capabilities: List[str],
    ) -> PluginExecutionResult:
        status = (
            ExecutionStatus.COMPLETED
            if result.status == "success"
            else ExecutionStatus.FAILED
        )
        return PluginExecutionResult(
            request_id=result.request_id,
            plugin_name=plugin_name,
            plugin_id=result.plugin_id,
            plugin_version=result.plugin_version,
            status=status,
            result=result.payload,
            error=result.error_detail,
            error_code=result.error_code,
            execution_time=max(float(result.latency_ms), 0.0) / 1000.0,
            started_at=result.created_at,
            completed_at=datetime.now(timezone.utc),
            metadata={
                "execution_id": result.execution_id,
                "source": result.source.value,
                "trust_tier": result.trust_tier.value,
                "result_trust": result.result_trust.value,
                "data_classification": result.data_classification.value,
                "side_effects": list(result.side_effects),
            },
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=str(session_id or ""),
            conversation_id=str(conversation_id or ""),
            correlation_id=str(result.correlation_id or ""),
            policy_decision_id=str(result.policy_decision_id or ""),
            requested_capabilities=list(requested_capabilities),
            granted_capabilities=list(granted_capabilities),
        )

    def _record_result(self, result: PluginExecutionResult) -> PluginExecutionResult:
        self._history.append(result)
        if len(self._history) > 1000:
            del self._history[:-1000]
        return result

    @staticmethod
    def _permission_granted(grants: List[str], required: str) -> bool:
        normalized = {str(value).strip() for value in grants if str(value).strip()}
        if "*" in normalized or required in normalized:
            return True
        if ":" in required and required.split(":", 1)[0] in normalized:
            return True
        return False

    async def execute_plugin(
        self,
        plugin_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        execution_mode: ExecutionMode = ExecutionMode.SANDBOX,
        timeout_seconds: int = 30,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        policy_decision_id: Optional[str] = None,
        authorized_plan: Optional[AuthorizedExecutionPlan] = None,
        allowed_capabilities: Optional[List[str]] = None,
        forbidden_capabilities: Optional[List[str]] = None,
    ) -> PluginExecutionResult:
        """Execute through RuntimePolicy and the one canonical extension executor."""
        del execution_mode  # Runtime isolation comes from the execution manifest.
        await self._ensure_initialized()
        request_id = str(uuid.uuid4())
        resolved_user = str(user_id or "").strip()
        resolved_tenant = str(tenant_id or "").strip()
        resolved_correlation = str(correlation_id or "").strip() or request_id
        requested_caps = list(allowed_capabilities or [])

        def failure(code: str, message: str) -> PluginExecutionResult:
            return self._record_result(
                self._failure(
                    request_id=request_id,
                    plugin_name=plugin_name,
                    code=code,
                    message=message,
                    user_id=resolved_user,
                    tenant_id=resolved_tenant,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    correlation_id=resolved_correlation,
                    policy_decision_id=policy_decision_id,
                    requested_capabilities=requested_caps,
                )
            )

        if not resolved_user or not resolved_tenant:
            return failure(
                "identity_scope_missing",
                "Plugin execution requires authenticated user and tenant scope",
            )

        try:
            validated_parameters = self._validate_parameter_contract(
                plugin_name, parameters or {}
            )
        except LookupError:
            return failure("plugin_not_found", "Plugin not found")
        except (TypeError, ValueError):
            return failure(
                "invalid_parameters",
                "Plugin parameters do not satisfy the manifest contract",
            )

        required_permissions = self._get_kernel().get_required_permissions(plugin_name)
        principal_permissions = list(permissions or [])
        missing_principal_permissions = [
            permission
            for permission in required_permissions
            if not self._permission_granted(principal_permissions, permission)
        ]
        if missing_principal_permissions:
            return failure(
                "permission_denied",
                "Plugin execution requires permissions: "
                + ", ".join(missing_principal_permissions),
            )
        for permission in required_permissions:
            if permission not in requested_caps:
                requested_caps.append(permission)

        if authorized_plan is not None and not isinstance(
            authorized_plan, AuthorizedExecutionPlan
        ):
            return failure(
                "authorized_plan_invalid",
                "Plugin execution requires a typed AuthorizedExecutionPlan",
            )

        if authorized_plan is None:
            if policy_decision_id:
                return failure(
                    "authorized_plan_required",
                    "A policy_decision_id alone cannot authorize plugin execution",
                )
            decision = await self._policy_enforcer.evaluate(
                PolicyEvaluationRequest(
                    user_id=resolved_user,
                    tenant_id=resolved_tenant,
                    session_id=session_id,
                    correlation_id=resolved_correlation,
                    roles=list(roles or []),
                    permissions=principal_permissions,
                    action="plugin_execution",
                    plugin_id=plugin_name,
                    requested_capabilities=requested_caps,
                    forbidden_capabilities=list(forbidden_capabilities or []),
                )
            )
            if not decision.allowed:
                policy_decision_id = decision.decision_id
                return failure(
                    "policy_denied", "Plugin execution denied by RuntimePolicy"
                )
            authorized_plan = decision.to_authorized_plan()
        elif policy_decision_id and policy_decision_id != authorized_plan.policy_decision_id:
            return failure(
                "policy_decision_mismatch",
                "policy_decision_id does not match AuthorizedExecutionPlan",
            )

        policy_decision_id = authorized_plan.policy_decision_id
        if not authorized_plan.matches_execution_scope(
            user_id=resolved_user,
            tenant_id=resolved_tenant,
            session_id=session_id,
            policy_decision_id=policy_decision_id,
        ):
            return failure(
                "authorized_scope_mismatch",
                "AuthorizedExecutionPlan does not match execution identity scope",
            )
        if plugin_name not in authorized_plan.allowed_plugins:
            return failure(
                "plugin_not_authorized",
                "Plugin is not present in AuthorizedExecutionPlan.allowed_plugins",
            )
        missing_plan_permissions = [
            permission
            for permission in required_permissions
            if not self._permission_granted(
                list(authorized_plan.allowed_capabilities), permission
            )
        ]
        if missing_plan_permissions:
            return failure(
                "permission_plan_mismatch",
                "AuthorizedExecutionPlan does not grant plugin permissions: "
                + ", ".join(missing_plan_permissions),
            )
        if not await ActionExecutionGate.authorize(authorized_plan, plugin_name):
            return failure(
                "action_gate_denied",
                "Plugin execution denied by ActionExecutionGate",
            )

        context = ExtensionExecutionContext(
            request_id=request_id,
            correlation_id=resolved_correlation,
            user_id=resolved_user,
            tenant_id=resolved_tenant,
            session_id=session_id,
            conversation_id=conversation_id,
            policy_decision_id=policy_decision_id,
            allowed_capabilities=list(authorized_plan.allowed_capabilities),
            resource_scope=dict(authorized_plan.resource_scope),
            audit_context={
                "user_roles": list(roles or []),
                "permissions": principal_permissions,
            },
        )
        canonical_request = ExtensionExecutionRequest(
            plugin_id=plugin_name,
            capability=PluginKernel.EXECUTE_CAPABILITY,
            payload=validated_parameters,
            context=context,
            authorized_plan=authorized_plan,
            timeout_override_ms=max(int(timeout_seconds), 1) * 1000,
        )
        try:
            canonical_result = await self._get_kernel().execute(canonical_request)
        except Exception as exc:
            logger.exception("Canonical plugin execution failed for %s", plugin_name)
            return failure("plugin_execution_error", str(exc))

        return self._record_result(
            self._adapt_result(
                canonical_result,
                plugin_name=plugin_name,
                user_id=resolved_user,
                tenant_id=resolved_tenant,
                session_id=session_id,
                conversation_id=conversation_id,
                requested_capabilities=requested_caps,
                granted_capabilities=list(authorized_plan.allowed_capabilities),
            )
        )

    async def cancel_execution(self, request_id: str) -> bool:
        """Cancellation is unsupported until the canonical executor exposes handles."""
        del request_id
        await self._ensure_initialized()
        return False

    def get_plugin(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return None
        return self.kernel.get_record(plugin_name)

    async def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        return self.get_plugin(plugin_name)

    async def list_plugins(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        plugins = self._get_kernel().list_records()
        if category:
            plugins = [
                plugin
                for plugin in plugins
                if str(getattr(plugin.get("manifest"), "category", "")) == category
            ]
        if enabled_only:
            plugins = [
                plugin
                for plugin in plugins
                if str(plugin.get("status")) in _ENABLED_STATES
            ]
        return list(plugins)

    def get_plugins_by_category(self, category: str) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(getattr(record.get("manifest"), "category", "")) == category
        ]

    def get_plugins_by_type(self, plugin_type: str) -> List[Dict[str, Any]]:
        return self.get_plugins_by_category(plugin_type)

    def get_plugins_by_status(self, status: str) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(record.get("status")) == status
        ]

    def get_available_plugins(self) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(record.get("status")) in _ENABLED_STATES
        ]

    def get_active_executions(self) -> List[PluginExecutionResult]:
        if not self.initialized or self.kernel is None:
            return []
        active_ids = set(self.kernel.active_executions())
        return [item for item in self._history if item.request_id in active_ids]

    def get_execution_history(self, limit: int = 100) -> List[PluginExecutionResult]:
        if limit <= 0:
            return []
        return list(self._history[-limit:])

    def get_plugin_runtime_stats(self, plugin_name: str) -> Dict[str, Any]:
        history = [
            item
            for item in self.get_execution_history(1000)
            if item.plugin_name == plugin_name
        ]
        successful = sum(
            item.status is ExecutionStatus.COMPLETED for item in history
        )
        last = next(
            (item.completed_at for item in reversed(history) if item.completed_at),
            None,
        )
        return {
            "execution_count": len(history),
            "success_rate": successful / len(history) if history else 0.0,
            "last_executed": last.isoformat() if last else None,
        }

    def _execution_metrics(self) -> Dict[str, Any]:
        completed = sum(
            item.status is ExecutionStatus.COMPLETED for item in self._history
        )
        failed = len(self._history) - completed
        total_time = sum(item.execution_time for item in self._history)
        return {
            "executions_total": len(self._history),
            "executions_successful": completed,
            "executions_failed": failed,
            "average_execution_time": (
                total_time / len(self._history) if self._history else 0.0
            ),
        }

    def get_service_stats(self) -> Dict[str, Any]:
        if not self.initialized or self.kernel is None:
            return {"initialized": False}
        return {
            "initialized": True,
            "registry_stats": self.kernel.registry_stats(),
            "execution_metrics": self._execution_metrics(),
            "active_executions": len(self.kernel.active_executions()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_metrics(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        stats = self.get_service_stats()
        registry = stats["registry_stats"]
        execution = stats["execution_metrics"]
        status_counts = registry.get("by_status", {})
        history = self.get_execution_history(100)
        usage = Counter(item.plugin_name for item in history)
        return {
            "total_plugins": int(registry.get("total_plugins", 0) or 0),
            "enabled_plugins": sum(
                int(status_counts.get(state, 0) or 0)
                for state in _ENABLED_STATES
            ),
            "total_executions": int(execution.get("executions_total", 0) or 0),
            "successful_executions": int(
                execution.get("executions_successful", 0) or 0
            ),
            "failed_executions": int(
                execution.get("executions_failed", 0) or 0
            ),
            "average_execution_time": float(
                execution.get("average_execution_time", 0.0) or 0.0
            ),
            "plugins_by_category": dict(registry.get("by_category", {})),
            "most_used_plugins": [
                {"plugin_name": name, "execution_count": count}
                for name, count in usage.most_common(10)
            ],
            "recent_executions": [
                {
                    "request_id": item.request_id,
                    "plugin_name": item.plugin_name,
                    "status": item.status.value,
                    "execution_time": item.execution_time,
                    "completed_at": (
                        item.completed_at.isoformat() if item.completed_at else None
                    ),
                    "tenant_id": item.tenant_id or None,
                    "correlation_id": item.correlation_id or None,
                }
                for item in reversed(history[-10:])
            ],
        }

    async def health_check(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        health: Dict[str, Any] = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }
        try:
            stats = self._get_kernel().registry_stats()
            health["components"]["registry"] = {
                "status": "healthy",
                "total_plugins": stats["total_plugins"],
                "enabled_plugins": sum(
                    int(stats["by_status"].get(state, 0) or 0)
                    for state in _ENABLED_STATES
                ),
            }
            health["components"]["execution_engine"] = {
                "status": "healthy",
                "authority": "ExtensionExecutionService",
                "active_executions": len(self._get_kernel().active_executions()),
                "total_executions": len(self._history),
            }
        except Exception:
            logger.exception("Plugin health check failed")
            health["status"] = "unhealthy"
            health["error_code"] = "plugin_health_check_failed"
        return health

    async def cleanup(self) -> None:
        if self.kernel is not None:
            await self.kernel.cleanup()
        self.initialized = False

    async def disable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_kernel().disable(plugin_name)

    async def enable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_kernel().enable(plugin_name)


_plugin_service: Optional[PluginService] = None


def get_plugin_service() -> PluginService:
    global _plugin_service
    if _plugin_service is None:
        _plugin_service = PluginService(_CANONICAL_PLUGIN_ROOT, _CANONICAL_PLUGIN_ROOT)
    return _plugin_service


async def initialize_plugin_service(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True,
) -> PluginService:
    global _plugin_service
    root = core_plugins_path or marketplace_path or _CANONICAL_PLUGIN_ROOT
    _plugin_service = PluginService(root, root)
    await _plugin_service.initialize(auto_discover)
    return _plugin_service


async def discover_and_register_all_plugins() -> Dict[str, bool]:
    service = get_plugin_service()
    await service.discover_plugins(force_refresh=True)
    return await service.validate_and_register_all_discovered()


async def execute_plugin_simple(
    plugin_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 30,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> PluginExecutionResult:
    return await get_plugin_service().execute_plugin(
        plugin_name,
        parameters=parameters or {},
        timeout_seconds=timeout_seconds,
        user_id=user_id,
        tenant_id=tenant_id,
    )


async def get_plugin_marketplace_info() -> Dict[str, Any]:
    """Compatibility name returning local catalog truth, never remote-market data."""
    service = get_plugin_service()
    await service._ensure_initialized()
    stats = service.get_service_stats()["registry_stats"]
    catalog = []
    for plugin in service.get_available_plugins():
        manifest = plugin.get("manifest")
        if manifest is None:
            continue
        catalog.append(
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "category": manifest.category,
                "type": manifest.category,
                "author": manifest.author,
            }
        )
    return {
        "total_plugins": stats.get("total_plugins", 0),
        "by_category": stats.get("by_category", {}),
        "by_type": stats.get("by_type", {}),
        "by_status": stats.get("by_status", {}),
        "available_plugins": catalog,
    }


__all__ = [
    "ExecutionMode",
    "ExecutionStatus",
    "PluginExecutionResult",
    "PluginService",
    "get_plugin_service",
    "initialize_plugin_service",
    "discover_and_register_all_plugins",
    "execute_plugin_simple",
    "get_plugin_marketplace_info",
]