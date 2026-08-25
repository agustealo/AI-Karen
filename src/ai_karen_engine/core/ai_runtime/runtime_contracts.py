from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capability_types import CapabilityId, ExecutionLayer


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    capability_id: CapabilityId
    input: dict[str, Any]

    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    requested_target: str | None = None
    preferred_model: str | None = None

    request_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityAttempt:
    target: str
    execution_layer: ExecutionLayer
    status: str
    runtime_engine: str | None = None
    provider_id: str | None = None
    extension_id: str | None = None
    model: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityExecutionResult:
    capability_id: CapabilityId
    output: Any

    requested_target: str | None
    resolved_target: str | None
    execution_layer: ExecutionLayer

    runtime_engine: str | None = None
    provider_id: str | None = None
    extension_id: str | None = None
    compatibility_profile: str | None = None

    requested_model: str | None = None
    actual_model: str | None = None

    response_source: str = "core_runtime"
    fallback_level: int = 0
    degraded_mode: bool = False
    degradation_type: str | None = None
    degradation_reason: str | None = None

    attempts: tuple[CapabilityAttempt, ...] = ()
    latency_ms: float = 0.0
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)