from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ProviderAttempt:
    """One attempt to fulfill a request with a specific provider/model."""

    provider: str
    model: str
    runtime_engine: str
    started_at: datetime
    duration_ms: float | None = None
    status: str | None = None
    error_code: str | None = None
    fallback_level: int | None = None


@dataclass(slots=True)
class PluginAction:
    """One plugin/tool execution within a trajectory."""

    plugin_id: str
    action: str
    policy_decision_id: str | None = None
    duration_ms: float | None = None
    status: str | None = None
    error_code: str | None = None


@dataclass(slots=True)
class ExecutionTrajectory:
    """Truthful record of what the runtime decided and executed.

    This is observational only. It does not control runtime behavior.
    It links to persisted conversation/memory records rather than
    duplicating raw content.
    """

    trajectory_id: str
    request_id: str | None = None
    correlation_id: str | None = None

    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    input_fingerprint: str | None = None

    intent: str | None = None
    intelligence_signals: dict[str, Any] = field(default_factory=dict)

    cortex_decision: dict[str, Any] | None = None

    policy_decision_id: str | None = None
    policy_allowed_capabilities: list[str] = field(default_factory=list)
    policy_denied_capabilities: list[str] = field(default_factory=list)

    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None

    requested_provider: str | None = None
    requested_model: str | None = None

    actual_provider: str | None = None
    actual_model: str | None = None
    runtime_engine: str | None = None

    provider_attempts: list[ProviderAttempt] = field(default_factory=list)

    fallback_level: int | None = None
    degraded_mode: bool | None = None
    degradation_reason: str | None = None

    memory_recall_refs: list[str] = field(default_factory=list)
    memory_recall_count: int | None = None

    plugin_actions: list[PluginAction] = field(default_factory=list)

    latencies: dict[str, float] = field(default_factory=dict)

    execution_status: str | None = None
    error_code: str | None = None

    response_source: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "trajectory_id": self.trajectory_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "input_fingerprint": self.input_fingerprint,
            "intent": self.intent,
            "intelligence_signals": self.intelligence_signals,
            "cortex_decision": self.cortex_decision,
            "policy_decision_id": self.policy_decision_id,
            "policy_allowed_capabilities": self.policy_allowed_capabilities,
            "policy_denied_capabilities": self.policy_denied_capabilities,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "actual_provider": self.actual_provider,
            "actual_model": self.actual_model,
            "runtime_engine": self.runtime_engine,
            "provider_attempts": [
                {
                    "provider": a.provider,
                    "model": a.model,
                    "runtime_engine": a.runtime_engine,
                    "started_at": a.started_at.isoformat(),
                    "duration_ms": a.duration_ms,
                    "status": a.status,
                    "error_code": a.error_code,
                    "fallback_level": a.fallback_level,
                }
                for a in self.provider_attempts
            ],
            "fallback_level": self.fallback_level,
            "degraded_mode": self.degraded_mode,
            "degradation_reason": self.degradation_reason,
            "memory_recall_refs": self.memory_recall_refs,
            "memory_recall_count": self.memory_recall_count,
            "plugin_actions": [
                {
                    "plugin_id": a.plugin_id,
                    "action": a.action,
                    "policy_decision_id": a.policy_decision_id,
                    "duration_ms": a.duration_ms,
                    "status": a.status,
                    "error_code": a.error_code,
                }
                for a in self.plugin_actions
            ],
            "latencies": self.latencies,
            "execution_status": self.execution_status,
            "error_code": self.error_code,
            "response_source": self.response_source,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return {k: v for k, v in data.items() if v is not None}
