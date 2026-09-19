"""Canonical application service for local-first plugin capabilities."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.policy import PolicyEvaluationRequest, RuntimePolicyEnforcer
from ai_karen_engine.services.plugin_discovery import PluginRegistry, initialize_plugin_registry
from ai_karen_engine.services.plugin_execution import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PluginExecutionEngine,
    initialize_plugin_execution_engine,
)

logger = logging.getLogger(__name__)
_ENABLED_STATES = {"registered", "loaded", "active"}


class PluginService:
    """Own plugin discovery, state, policy-gated execution, and runtime metrics."""

    def __init__(
        self,
        marketplace_path: Optional[Path] = None,
        core_plugins_path: Optional[Path] = None,
    ) -> None:
        self.registry: Optional[PluginRegistry] = None
        self.execution_engine: Optional[PluginExecutionEngine] = None
        self.marketplace_path = marketplace_path
        self.core_plugins_path = core_plugins_path
        self.initialized = False
        self._policy_enforcer = RuntimePolicyEnforcer()

    async def initialize(self, auto_discover: bool = True) -> None:
        if self.initialized:
            return
        self.registry = await initialize_plugin_registry(
            self.marketplace_path,
            self.core_plugins_path,
            auto_discover=auto_discover,
        )
        self.execution_engine = await initialize_plugin_execution_engine(self.registry)
        self.initialized = True

    async def _ensure_initialized(self) -> None:
        if not self.initialized:
            await self.initialize()

    def _get_registry(self) -> PluginRegistry:
        if self.registry is None:
            raise RuntimeError("Plugin registry is not initialized")
        return self.registry

    def _get_execution_engine(self) -> PluginExecutionEngine:
        if self.execution_engine is None:
            raise RuntimeError("Plugin execution engine is not initialized")
        return self.execution_engine

    async def discover_plugins(
        self, force_refresh: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        await self._ensure_initialized()
        return await self._get_registry().discover_plugins(force_refresh)

    async def validate_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_registry().validate_plugin(plugin_name)

    async def register_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_registry().register_plugin(plugin_name)

    async def validate_and_register_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        registry = self._get_registry()
        return (
            await registry.register_plugin(plugin_name)
            if await registry.validate_plugin(plugin_name)
            else False
        )

    async def validate_and_register_all_discovered(self) -> Dict[str, bool]:
        """Register every discovered record using the registry's list contract."""
        await self._ensure_initialized()
        results: Dict[str, bool] = {}
        for metadata in self._get_registry().get_plugins_by_status("discovered"):
            manifest = metadata.get("manifest")
            name = str(getattr(manifest, "name", "") or "")
            if not name:
                continue
            try:
                results[name] = await self.validate_and_register_plugin(name)
            except Exception:
                logger.exception("Plugin registration failed for %s", name)
                results[name] = False
        return results

    async def refresh_plugins(self) -> int:
        await self._ensure_initialized()
        await self.discover_plugins(force_refresh=True)
        await self.validate_and_register_all_discovered()
        return len(self._get_registry().get_all_plugins())

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
        metadata = self._get_registry().get_plugin(plugin_name)
        if metadata is None:
            raise LookupError(plugin_name)
        manifest = metadata.get("manifest")
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

    async def execute_plugin(
        self,
        plugin_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        execution_mode: ExecutionMode = ExecutionMode.SANDBOX,
        timeout_seconds: int = 30,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        policy_decision_id: Optional[str] = None,
        allowed_capabilities: Optional[List[str]] = None,
        forbidden_capabilities: Optional[List[str]] = None,
    ) -> ExecutionResult:
        """Execute through RuntimePolicy using authoritative user and tenant scope."""
        await self._ensure_initialized()
        resolved_user = str(user_id or "").strip()
        resolved_tenant = str(tenant_id or "").strip()
        resolved_correlation = str(correlation_id or "").strip()
        requested_caps = list(allowed_capabilities or [])

        def failure(code: str, message: str) -> ExecutionResult:
            return ExecutionResult(
                request_id=str(uuid.uuid4()),
                plugin_name=plugin_name,
                status=ExecutionStatus.FAILED,
                error=message,
                error_code=code,
                user_id=resolved_user,
                tenant_id=resolved_tenant,
                correlation_id=resolved_correlation,
                requested_capabilities=requested_caps,
                granted_capabilities=[],
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

        authorized_plan = None
        if not policy_decision_id:
            policy_request = PolicyEvaluationRequest(
                user_id=resolved_user,
                tenant_id=resolved_tenant,
                session_id=session_id,
                correlation_id=resolved_correlation or None,
                roles=list(roles or []),
                permissions=list(permissions or []),
                action="plugin_execution",
                plugin_id=plugin_name,
                requested_capabilities=requested_caps,
                forbidden_capabilities=list(forbidden_capabilities or []),
            )
            decision = await self._policy_enforcer.evaluate(policy_request)
            if not decision.allowed:
                denied = failure(
                    "policy_denied", "Plugin execution denied by RuntimePolicy"
                )
                denied.policy_decision_id = decision.decision_id
                return denied
            policy_decision_id = decision.decision_id
            allowed_capabilities = list(decision.allowed_capabilities)
            forbidden_capabilities = list(decision.denied_capabilities)
            authorized_plan = decision.to_authorized_plan()

        request = ExecutionRequest(
            plugin_name=plugin_name,
            parameters=validated_parameters,
            execution_mode=execution_mode,
            timeout_seconds=timeout_seconds,
            user_id=resolved_user,
            session_id=session_id,
            policy_decision_id=policy_decision_id,
            allowed_capabilities=list(allowed_capabilities or []),
            forbidden_capabilities=list(forbidden_capabilities or []),
        )
        result = await self._get_execution_engine().execute_plugin(
            request, plan=authorized_plan
        )
        result.user_id = resolved_user
        result.tenant_id = resolved_tenant
        result.correlation_id = resolved_correlation
        return result

    async def cancel_execution(self, request_id: str) -> bool:
        await self._ensure_initialized()
        return await self._get_execution_engine().cancel_execution(request_id)

    def get_plugin(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if not self.initialized or self.registry is None:
            return None
        return self.registry.get_plugin(plugin_name)

    async def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        return self.get_plugin(plugin_name)

    async def list_plugins(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        registry = self._get_registry()
        plugins = (
            registry.get_plugins_by_category(category)
            if category
            else registry.get_all_plugins()
        )
        if enabled_only:
            plugins = [
                plugin
                for plugin in plugins
                if plugin.get("status") in _ENABLED_STATES
            ]
        return list(plugins)

    def get_plugins_by_category(self, category: str) -> List[Dict[str, Any]]:
        return (
            self.registry.get_plugins_by_category(category)
            if self.initialized and self.registry
            else []
        )

    def get_plugins_by_type(self, plugin_type: str) -> List[Dict[str, Any]]:
        return (
            self.registry.get_plugins_by_type(plugin_type)
            if self.initialized and self.registry
            else []
        )

    def get_plugins_by_status(self, status: str) -> List[Dict[str, Any]]:
        return (
            self.registry.get_plugins_by_status(status)
            if self.initialized and self.registry
            else []
        )

    def get_available_plugins(self) -> List[Dict[str, Any]]:
        if not self.initialized or self.registry is None:
            return []
        return [
            plugin
            for plugin in self.registry.get_all_plugins()
            if plugin.get("status") in _ENABLED_STATES
        ]

    def get_active_executions(self) -> List[ExecutionResult]:
        return (
            self.execution_engine.get_active_executions()
            if self.initialized and self.execution_engine
            else []
        )

    def get_execution_history(self, limit: int = 100) -> List[ExecutionResult]:
        return (
            self.execution_engine.get_execution_history(limit)
            if self.initialized and self.execution_engine
            else []
        )

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

    def get_service_stats(self) -> Dict[str, Any]:
        if not self.initialized:
            return {"initialized": False}
        return {
            "initialized": True,
            "registry_stats": (
                self.registry.get_registry_stats() if self.registry else {}
            ),
            "execution_metrics": (
                self.execution_engine.get_execution_metrics()
                if self.execution_engine
                else {}
            ),
            "active_executions": len(self.get_active_executions()),
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
                        item.completed_at.isoformat()
                        if item.completed_at
                        else None
                    ),
                    "tenant_id": item.tenant_id or None,
                    "correlation_id": item.correlation_id or None,
                }
                for item in reversed(history[-10:])
            ],
        }

    async def health_check(self) -> Dict[str, Any]:
        """Return safe health truth without serializing internal exceptions."""
        health: Dict[str, Any] = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }
        try:
            if not self.initialized:
                health["status"] = "unhealthy"
                health["components"]["initialization"] = {"status": "failed"}
                return health
            registry_stats = (
                self.registry.get_registry_stats() if self.registry else None
            )
            if registry_stats is None:
                health["status"] = "degraded"
                health["components"]["registry"] = {"status": "missing"}
            else:
                health["components"]["registry"] = {
                    "status": "healthy",
                    "total_plugins": registry_stats["total_plugins"],
                    "registered_plugins": registry_stats["by_status"].get(
                        "registered", 0
                    ),
                }
            if self.execution_engine is None:
                health["status"] = "degraded"
                health["components"]["execution_engine"] = {"status": "missing"}
            else:
                metrics = self.execution_engine.get_execution_metrics()
                health["components"]["execution_engine"] = {
                    "status": "healthy",
                    "active_executions": len(
                        self.execution_engine.get_active_executions()
                    ),
                    "total_executions": metrics["executions_total"],
                    "success_rate": metrics["executions_successful"]
                    / max(metrics["executions_total"], 1),
                }
        except Exception:
            logger.exception("Plugin health check failed")
            health["status"] = "unhealthy"
            health["error_code"] = "plugin_health_check_failed"
        return health

    async def cleanup(self) -> None:
        if self.execution_engine:
            await self.execution_engine.cleanup()
        self.initialized = False

    async def disable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        plugin = self.get_plugin(plugin_name)
        if plugin is None:
            return False
        plugin["status"] = "disabled"
        return True

    async def enable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        plugin = self.get_plugin(plugin_name)
        if plugin is None:
            return False
        plugin["status"] = "registered"
        return True


_plugin_service: Optional[PluginService] = None


def get_plugin_service() -> PluginService:
    global _plugin_service
    if _plugin_service is None:
        path = Path("src/ai_karen_engine/extensions/plugins")
        _plugin_service = PluginService(path, path)
    return _plugin_service


async def initialize_plugin_service(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True,
) -> PluginService:
    global _plugin_service
    canonical = Path("src/ai_karen_engine/extensions/plugins")
    _plugin_service = PluginService(
        marketplace_path or canonical,
        core_plugins_path or canonical,
    )
    await _plugin_service.initialize(auto_discover)
    if auto_discover:
        await _plugin_service.validate_and_register_all_discovered()
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
) -> ExecutionResult:
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
                "type": getattr(manifest, "plugin_type", None)
                or manifest.category,
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
