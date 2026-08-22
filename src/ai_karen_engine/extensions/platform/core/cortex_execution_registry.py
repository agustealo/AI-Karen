"""Unified registry/dispatch interface for extension and plugin execution.

Production owner: extensions/unified/core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional


@dataclass
class CortexExecutionContext:
    plugin_name: str
    user_ctx: Dict[str, Any]
    query: Any
    context: Optional[Dict[str, Any]] = None
    stream: Optional[Callable[[Dict[str, Any]], None]] = None


@dataclass
class CortexAuditEvent:
    plugin_name: str
    outcome: str
    stage: str
    detail: str


@dataclass
class CortexPluginRecord:
    name: str
    handler: Any
    origin: str
    manifest: Dict[str, Any] = field(default_factory=dict)


class CortexExecutionRegistry:
    """Single discovery/permission/dispatch interface used by routes/runtime."""

    def __init__(self) -> None:
        self._plugins: Dict[str, CortexPluginRecord] = {}
        self._audit_events: List[CortexAuditEvent] = []

    @property
    def audit_events(self) -> List[CortexAuditEvent]:
        return list(self._audit_events)

    def register_plugins(self, records: Iterable[CortexPluginRecord]) -> None:
        for record in records:
            self._plugins[record.name] = record

    def discover(self) -> Dict[str, CortexPluginRecord]:
        return dict(self._plugins)

    def execute(self, execution_context: CortexExecutionContext) -> Any:
        record = self._plugins.get(execution_context.plugin_name)
        if not record:
            self._emit_audit(record_name=execution_context.plugin_name, outcome="failed", stage="discovery", detail="plugin_not_found")
            raise KeyError(f"Plugin '{execution_context.plugin_name}' not found")

        self._emit_stream(execution_context, {"event": "tool.discovery", "plugin": record.name})

        # 1) CORTEX eligibility
        if not self._is_cortex_eligible(execution_context.user_ctx):
            self._emit_audit(record.name, "denied", "cortex_eligibility", "user_ineligible")
            raise PermissionError("CORTEX eligibility denied")

        self._emit_stream(execution_context, {"event": "tool.cortex_eligible", "plugin": record.name})

        # 2) RBAC + manifest
        self._validate_rbac(record, execution_context.user_ctx)
        self._validate_manifest(record)
        self._emit_stream(execution_context, {"event": "tool.validated", "plugin": record.name})

        # 3) execution
        try:
            output = self._invoke(record, execution_context)
            self._emit_stream(execution_context, {"event": "tool.executed", "plugin": record.name})
            # 4) audit success
            self._emit_audit(record.name, "success", "execution", "ok")
            # 5) safe output injection
            safe = self._safe_output_injection(output)
            self._emit_stream(execution_context, {"event": "tool.output_injected", "plugin": record.name})
            return safe
        except Exception as exc:
            self._emit_audit(record.name, "failed", "execution", str(exc))
            self._emit_stream(execution_context, {"event": "tool.execution_failed", "plugin": record.name, "error": str(exc)})
            raise

    def _validate_rbac(self, record: CortexPluginRecord, user_ctx: Dict[str, Any]) -> None:
        required = set(record.manifest.get("required_roles", []))
        roles = set(user_ctx.get("roles", []))
        if required and not (required & roles):
            self._emit_audit(record.name, "denied", "rbac", "missing_required_role")
            raise PermissionError("RBAC denied")

    def _validate_manifest(self, record: CortexPluginRecord) -> None:
        if not record.manifest.get("entrypoint"):
            self._emit_audit(record.name, "denied", "manifest_validation", "missing_entrypoint")
            raise ValueError("Manifest validation failed: missing entrypoint")

    def _invoke(self, record: CortexPluginRecord, execution_context: CortexExecutionContext) -> Any:
        handler = record.handler
        if hasattr(handler, "run"):
            return handler.run(execution_context.user_ctx, execution_context.query, execution_context.context)
        if hasattr(handler, "main"):
            return handler.main(execution_context.user_ctx, execution_context.query, execution_context.context)
        raise RuntimeError(f"No runnable entry for plugin: {handler}")

    def _is_cortex_eligible(self, user_ctx: Dict[str, Any]) -> bool:
        return bool(user_ctx.get("cortex_eligible", False))

    def _safe_output_injection(self, output: Any) -> Any:
        if isinstance(output, dict):
            sanitized = dict(output)
            sanitized.pop("debug_internal", None)
            return sanitized
        return output

    def _emit_audit(self, record_name: str, outcome: str, stage: str, detail: str) -> None:
        self._audit_events.append(CortexAuditEvent(record_name, outcome, stage, detail))

    def _emit_stream(self, execution_context: CortexExecutionContext, event: Dict[str, Any]) -> None:
        if execution_context.stream:
            execution_context.stream(event)
