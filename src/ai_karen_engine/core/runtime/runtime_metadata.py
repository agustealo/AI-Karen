from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .runtime_attempt import RuntimeAttempt

ExecutionLayer = Literal["core", "provider", "extension", "emergency"]
ResponseSource = Literal[
    "core_runtime",
    "provider_runtime",
    "extension_runtime",
    "fallback_provider_runtime",
    "fallback_core_runtime",
    "fallback_extension_runtime",
    "emergency_static",
    "runtime_configuration_error",
]


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    requested_target: str | None
    resolved_target: str | None
    execution_layer: ExecutionLayer

    response_source: ResponseSource

    runtime_engine: str | None = None
    provider_id: str | None = None
    extension_id: str | None = None
    compatibility_profile: str | None = None

    requested_model: str | None = None
    actual_model: str | None = None

    fallback_level: int = 0
    degraded_mode: bool = False
    degradation_type: str | None = None
    degradation_reason: str | None = None

    attempts: tuple[RuntimeAttempt, ...] = ()

    latency_ms: float = 0.0
    request_id: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "requested_target": self.requested_target,
            "resolved_target": self.resolved_target,
            "execution_layer": self.execution_layer,
            "response_source": self.response_source,
            "runtime_engine": self.runtime_engine,
            "provider_id": self.provider_id,
            "extension_id": self.extension_id,
            "compatibility_profile": self.compatibility_profile,
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "fallback_level": self.fallback_level,
            "degraded_mode": self.degraded_mode,
            "degradation_type": self.degradation_type,
            "degradation_reason": self.degradation_reason,
            "attempts": [asdict(attempt) for attempt in self.attempts],
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
        }
