from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RuntimeEventType(str, Enum):
    """Canonical runtime event types.

    These cover the full execution path from request ingress to final response.
    """

    # Request lifecycle
    REQUEST_RECEIVED = "request.received"
    REQUEST_STARTED = "request.started"
    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    REQUEST_CANCELLED = "request.cancelled"
    REQUEST_TIMEOUT = "request.timeout"

    # Intelligence layer
    INTELLIGENCE_STARTED = "intelligence.started"
    INTELLIGENCE_COMPLETED = "intelligence.completed"
    INTELLIGENCE_FAILED = "intelligence.failed"
    INTELLIGENCE_DEGRADED = "intelligence.degraded"

    # CORTEX layer
    CORTEX_DECISION = "cortex.decision"
    CORTEX_ANALYSIS_STARTED = "cortex.analysis.started"
    CORTEX_ANALYSIS_COMPLETED = "cortex.analysis.completed"
    CORTEX_REASONING_STARTED = "cortex.reasoning.started"
    CORTEX_REASONING_COMPLETED = "cortex.reasoning.completed"

    # Policy layer
    POLICY_EVALUATED = "policy.evaluated"
    POLICY_VALIDATION_PASSED = "policy.validation_passed"
    POLICY_VALIDATION_FAILED = "policy.validation_failed"
    POLICY_DECISION_MADE = "policy.decision_made"

    # Memory layer
    MEMORY_RECALL_STARTED = "memory.recall.started"
    MEMORY_RECALL_COMPLETED = "memory.recall.completed"
    MEMORY_RECALL_FAILED = "memory.recall.failed"
    MEMORY_STORAGE_STARTED = "memory.storage.started"
    MEMORY_STORAGE_COMPLETED = "memory.storage.completed"
    MEMORY_STORAGE_FAILED = "memory.storage.failed"

    # PromptRuntime layer
    PROMPT_ASSEMBLY_STARTED = "prompt.assembly_started"
    PROMPT_ASSEMBLY_COMPLETED = "prompt.assembly_completed"
    PROMPT_ASSEMBLY_FAILED = "prompt.assembly_failed"
    PROMPT_TRUNCATION_APPLIED = "prompt.truncation_applied"
    PROMPT_VALIDATION_PASSED = "prompt.validation_passed"
    PROMPT_VALIDATION_FAILED = "prompt.validation_failed"

    # ExpressionGateway layer
    EXPRESSION_GATEWAY_STARTED = "expression.gateway_started"
    EXPRESSION_GATEWAY_COMPLETED = "expression.gateway_completed"
    EXPRESSION_GATEWAY_FAILED = "expression.gateway_failed"

    # Provider layer
    PROVIDER_SELECTION = "provider.selection"
    PROVIDER_ATTEMPT_STARTED = "provider.attempt.started"
    PROVIDER_ATTEMPT_COMPLETED = "provider.attempt.completed"
    PROVIDER_ATTEMPT_FAILED = "provider.attempt.failed"
    PROVIDER_FALLBACK = "provider.fallback"
    PROVIDER_HEALTH_CHANGED = "provider.health.changed"
    PROVIDER_AVAILABLE = "provider.available"
    PROVIDER_UNAVAILABLE = "provider.unavailable"

    # Runtime layer
    RUNTIME_STARTUP_STARTED = "runtime.startup.started"
    RUNTIME_STARTUP_COMPLETED = "runtime.startup.completed"
    RUNTIME_STARTUP_FAILED = "runtime.startup.failed"
    RUNTIME_CAPABILITIES_READY = "runtime.capabilities.ready"
    RUNTIME_DEGRADED = "runtime.degraded"
    RUNTIME_RECOVERY_STARTED = "runtime.recovery.started"
    RUNTIME_RECOVERY_COMPLETED = "runtime.recovery.completed"

    # Plugin/Extension layer
    PLUGIN_DISCOVERY_STARTED = "plugin.discovery_started"
    PLUGIN_DISCOVERY_COMPLETED = "plugin.discovery_completed"
    PLUGIN_EXECUTION_STARTED = "plugin.execution_started"
    PLUGIN_EXECUTION_COMPLETED = "plugin.execution_completed"
    PLUGIN_EXECUTION_FAILED = "plugin.execution_failed"
    PLUGIN_VALIDATION_PASSED = "plugin.validation_passed"
    PLUGIN_VALIDATION_FAILED = "plugin.validation_failed"

    # Workflow layer
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_STEP_STARTED = "workflow.step_started"
    WORKFLOW_STEP_COMPLETED = "workflow.step_completed"
    WORKFLOW_STEP_FAILED = "workflow.step_failed"

    # Tool layer
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    TOOL_TIMEOUT = "tool.timeout"

    # Persistence layer
    PERSISTENCE_STARTED = "persistence.started"
    PERSISTENCE_COMPLETED = "persistence.completed"
    PERSISTENCE_FAILED = "persistence.failed"
    CACHE_HIT = "cache.hit"
    CACHE_MISS = "cache.miss"

    # Learning layer
    LEARNING_FEATURE_SNAPSHOT_RECORDED = "learning.feature_snapshot.recorded"
    LEARNING_DECISION_OBSERVATION_RECORDED = "learning.decision_observation.recorded"
    LEARNING_OUTCOME_LINKED = "learning.outcome_linked"
    LEARNING_DATASET_BUILD_STARTED = "learning.dataset.build_started"
    LEARNING_DATASET_BUILD_COMPLETED = "learning.dataset.build_completed"
    LEARNING_DATASET_BUILD_FAILED = "learning.dataset.build_failed"
    LEARNING_RECORDING_FAILED = "learning.recording_failed"
    LEARNING_MODEL_UPDATED = "learning.model_updated"

    # Security layer
    SECURITY_CHECK_PASSED = "security.check_passed"
    SECURITY_CHECK_FAILED = "security.check_failed"
    AUTHENTICATION_SUCCESS = "authentication.success"
    AUTHENTICATION_FAILED = "authentication.failed"
    AUTHORIZATION_SUCCESS = "authorization.success"
    AUTHORIZATION_FAILED = "authorization.failed"

    # Performance layer
    PERFORMANCE_METRIC_RECORDED = "performance.metric_recorded"
    PERFORMANCE_THRESHOLD_EXCEEDED = "performance.threshold_exceeded"
    BUDGET_EXHAUSTED = "budget.exhausted"

    # Observability layer
    OBSERVABILITY_EVENT_EMITTED = "observability.event_emitted"
    OBSERVABILITY_BUFFER_FLUSHED = "observability.buffer_flushed"
    OBSERVABILITY_ERROR = "observability.error"


@dataclass(slots=True)
class RuntimeEvent:
    """Single canonical event contract for runtime observability.

    Not every event needs every field, but this contract defines the vocabulary.
    """

    event_id: str
    event_type: RuntimeEventType
    timestamp: datetime = field(default_factory=datetime.utcnow)

    correlation_id: str | None = None
    request_id: str | None = None

    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    intent: str | None = None

    provider: str | None = None
    model: str | None = None
    runtime_engine: str | None = None
    fallback_level: int | None = None
    degraded_mode: bool | None = None
    response_source: str | None = None

    policy_decision_id: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None

    memory_recall_count: int | None = None

    plugin_id: str | None = None
    plugin_version: str | None = None

    duration_ms: float | None = None
    status: str | None = None

    error_type: str | None = None
    error_code: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "intent": self.intent,
            "provider": self.provider,
            "model": self.model,
            "runtime_engine": self.runtime_engine,
            "fallback_level": self.fallback_level,
            "degraded_mode": self.degraded_mode,
            "response_source": self.response_source,
            "policy_decision_id": self.policy_decision_id,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "memory_recall_count": self.memory_recall_count,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_type": self.error_type,
            "error_code": self.error_code,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return {k: v for k, v in data.items() if v is not None}
