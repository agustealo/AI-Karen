from __future__ import annotations

from enum import Enum

class RuntimeEvents(str, Enum):
    REQUEST_STARTED = "runtime.request.started"
    REQUEST_COMPLETED = "runtime.request.completed"
    REQUEST_FAILED = "runtime.request.failed"
    STAGE_STARTED = "runtime.stage.started"
    STAGE_COMPLETED = "runtime.stage.completed"
    STAGE_FAILED = "runtime.stage.failed"
    DEGRADED = "runtime.degraded"
    STARTUP_STARTED = "runtime.startup.started"
    STARTUP_COMPLETED = "runtime.startup.completed"
    STARTUP_FAILED = "runtime.startup.failed"
    CAPABILITIES_READY = "runtime.capabilities.ready"

class ExpressionEvents(str, Enum):
    TASK_STARTED = "expression.task.started"
    ENGINE_SELECTED = "expression.engine.selected"
    ENGINE_SKIPPED = "expression.engine.skipped"
    REQUEST_STARTED = "expression.engine.request.started"
    REQUEST_COMPLETED = "expression.engine.request.completed"
    REQUEST_FAILED = "expression.engine.request.failed"
    OUTPUT_INVALID = "expression.output.invalid"
    FALLBACK_STARTED = "expression.fallback.started"
    FALLBACK_COMPLETED = "expression.fallback.completed"
    EMERGENCY_USED = "expression.emergency.used"

class ProviderEvents(str, Enum):
    SELECTION_STARTED = "provider.selection.started"
    SELECTION_COMPLETED = "provider.selection.completed"
    ATTEMPT_STARTED = "provider.attempt.started"
    ATTEMPT_COMPLETED = "provider.attempt.completed"
    ATTEMPT_FAILED = "provider.attempt.failed"
    RETRY = "provider.retry"
    FALLBACK = "provider.fallback"
    EXHAUSTED = "provider.exhausted"
    POLICY_REJECTED = "provider.policy.rejected"
    CIRCUIT_OPEN = "provider.circuit.open"
    HEALTH_CHANGED = "provider.health.changed"
    AVAILABLE = "provider.available"
    UNAVAILABLE = "provider.unavailable"


class RoutingEvents(str, Enum):
    REQUESTED = "routing.requested"
    EVALUATED = "routing.evaluated"
    SELECTED = "routing.selected"
    REJECTED = "routing.rejected"

class MemoryEvents(str, Enum):
    ACTIVATION_STARTED = "memory.activation.started"
    ACTIVATION_COMPLETED = "memory.activation.completed"
    RECALL_STARTED = "memory.recall.started"
    RECALL_STORE_STARTED = "memory.recall.store.started"
    RECALL_STORE_COMPLETED = "memory.recall.store.completed"
    RECALL_FUSION_COMPLETED = "memory.recall.fusion.completed"
    RECALL_DEGRADED = "memory.recall.degraded"
    GUARD_STARTED = "memory.guard.started"
    GUARD_COMPLETED = "memory.guard.completed"
    WRITEBACK_STARTED = "memory.writeback.started"
    WRITEBACK_COMPLETED = "memory.writeback.completed"
    WRITEBACK_SKIPPED = "memory.writeback.skipped"
    WRITEBACK_FAILED = "memory.writeback.failed"
    PROJECTION_STARTED = "memory.projection.started"
    PROJECTION_COMPLETED = "memory.projection.completed"
    PROJECTION_FAILED = "memory.projection.failed"

class ToolEvents(str, Enum):
    EXECUTION_STARTED = "tool.execution.started"
    EXECUTION_COMPLETED = "tool.execution.completed"
    EXECUTION_FAILED = "tool.execution.failed"
    PLUGIN_STARTED = "plugin.execution.started"
    PLUGIN_COMPLETED = "plugin.execution.completed"
    PLUGIN_FAILED = "plugin.execution.failed"
    POLICY_REJECTED = "plugin.policy.rejected"

class SecurityEvents(str, Enum):
    AUTH_STARTED = "security.auth.started"
    AUTH_COMPLETED = "security.auth.completed"
    AUTH_FAILED = "security.auth.failed"
    RBAC_DENIED = "security.rbac.denied"
    TENANT_VIOLATION = "security.tenant_violation"
    AUDIT_CREATED = "audit.event.created"

class ConfigEvents(str, Enum):
    STARTUP_STARTED = "startup.validation.started"
    STARTUP_COMPLETED = "startup.validation.completed"
    STARTUP_FAILED = "startup.validation.failed"
    LOADED = "config.loaded"
    INVALID = "config.invalid"
    LEGACY_DETECTED = "legacy.residue.detected"
