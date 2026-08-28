from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Canonical operational event taxonomy.

    One vocabulary for the whole execution path. Provider, prompt, extension,
    memory, and policy code emit these rather than defining incompatible names.
    """

    # Request lifecycle
    REQUEST_RECEIVED = "request.received"
    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    REQUEST_CANCELLED = "request.cancelled"

    # Auth
    AUTH_STARTED = "auth.started"
    AUTH_SUCCEEDED = "auth.succeeded"
    AUTH_FAILED = "auth.failed"

    # Intelligence / cortex / policy
    INTELLIGENCE_STARTED = "intelligence.started"
    INTELLIGENCE_COMPLETED = "intelligence.completed"
    CORTEX_STARTED = "cortex.started"
    CORTEX_COMPLETED = "cortex.completed"
    # Compatibility alias for legacy ChatRuntime emitters. New code should use
    # CORTEX_COMPLETED; remove after the runtime caller is migrated.
    CORTEX_DECISION = "cortex.completed"
    POLICY_STARTED = "policy.started"
    POLICY_COMPLETED = "policy.completed"
    POLICY_DENIED = "policy.denied"

    # Memory
    MEMORY_RECALL_STARTED = "memory.recall.started"
    MEMORY_RECALL_COMPLETED = "memory.recall.completed"

    # Prompt
    PROMPT_STARTED = "prompt.started"
    PROMPT_COMPLETED = "prompt.completed"
    PROMPT_FAILED = "prompt.failed"

    # Provider / model execution
    PROVIDER_SELECTION_COMPLETED = "provider.selection.completed"
    # Compatibility alias for legacy ChatRuntime emitters. New code should use
    # PROVIDER_SELECTION_COMPLETED; remove after the runtime caller is migrated.
    PROVIDER_SELECTION = "provider.selection.completed"
    PROVIDER_EXECUTION_STARTED = "provider.execution.started"
    PROVIDER_EXECUTION_COMPLETED = "provider.execution.completed"
    PROVIDER_EXECUTION_FAILED = "provider.execution.failed"
    PROVIDER_FALLBACK = "provider.fallback"

    # Workflow
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Extensions / plugins
    EXTENSION_RESOLUTION_STARTED = "extension.resolution.started"
    EXTENSION_EXECUTION_STARTED = "extension.execution.started"
    EXTENSION_EXECUTION_COMPLETED = "extension.execution.completed"
    EXTENSION_EXECUTION_FAILED = "extension.execution.failed"

    # Tools
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    # Persistence
    PERSISTENCE_STARTED = "persistence.started"
    PERSISTENCE_COMPLETED = "persistence.completed"
    PERSISTENCE_FAILED = "persistence.failed"


class ErrorCategory(str, Enum):
    """Structured error taxonomy for emitted events.

    Operational systems (metrics, alerts, diagnostics) key off these rather
    than arbitrary exception type names.
    """

    AUTH = "AUTH"
    POLICY = "POLICY"
    PROVIDER = "PROVIDER"
    MODEL = "MODEL"
    PROMPT = "PROMPT"
    MEMORY = "MEMORY"
    PLUGIN = "PLUGIN"
    TOOL = "TOOL"
    PERSISTENCE = "PERSISTENCE"
    VALIDATION = "VALIDATION"
    CONFIGURATION = "CONFIGURATION"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"


class OperationalState(str, Enum):
    """Coarse operational health of a runtime stage."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


HIGH_CARDINALITY_LABELS: frozenset[str] = frozenset(
    {
        "user_id",
        "tenant_id",
        "session_id",
        "conversation_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "span_id",
        "event_id",
        "prompt",
        "url",
        "error_message",
        "message",
    }
)


@dataclass(slots=True)
class ExecutionEvent:
    """Canonical operational event envelope."""

    event_id: str
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)

    request_id: str | None = None
    correlation_id: str | None = None

    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    status: str | None = None
    error_category: ErrorCategory | None = None
    error_type: str | None = None
    error_code: str | None = None
    retryable: bool | None = None

    duration_ms: float | None = None

    requested_target: str | None = None
    resolved_target: str | None = None
    provider: str | None = None
    model: str | None = None
    runtime_engine: str | None = None
    execution_layer: str | None = None
    response_source: str | None = None
    fallback_level: int | None = None
    degraded_mode: bool | None = None
    degradation_type: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "error_category": self.error_category.value if self.error_category else None,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "duration_ms": self.duration_ms,
            "requested_target": self.requested_target,
            "resolved_target": self.resolved_target,
            "provider": self.provider,
            "model": self.model,
            "runtime_engine": self.runtime_engine,
            "execution_layer": self.execution_layer,
            "response_source": self.response_source,
            "fallback_level": self.fallback_level,
            "degraded_mode": self.degraded_mode,
            "degradation_type": self.degradation_type,
            "metadata": dict(self.metadata),
        }
        return {k: v for k, v in data.items() if v is not None}
