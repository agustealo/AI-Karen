from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RuntimeEventType(str, Enum):
    """Canonical runtime event types.

    These cover the full execution path from request ingress to final response.
    """

    REQUEST_RECEIVED = "request.received"

    INTELLIGENCE_STARTED = "intelligence.started"
    INTELLIGENCE_COMPLETED = "intelligence.completed"

    CORTEX_DECISION = "cortex.decision"

    POLICY_EVALUATED = "policy.evaluated"

    MEMORY_RECALL_STARTED = "memory.recall.started"
    MEMORY_RECALL_COMPLETED = "memory.recall.completed"

    PROMPT_ASSEMBLED = "prompt.assembled"

    PROVIDER_SELECTION = "provider.selection"

    PROVIDER_ATTEMPT_STARTED = "provider.attempt.started"
    PROVIDER_ATTEMPT_COMPLETED = "provider.attempt.completed"
    PROVIDER_ATTEMPT_FAILED = "provider.attempt.failed"

    FALLBACK_APPLIED = "fallback.applied"
    RUNTIME_DEGRADED = "runtime.degraded"

    PLUGIN_STARTED = "plugin.started"
    PLUGIN_COMPLETED = "plugin.completed"
    PLUGIN_FAILED = "plugin.failed"

    PERSISTENCE_COMPLETED = "persistence.completed"
    PERSISTENCE_FAILED = "persistence.failed"

    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"


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
