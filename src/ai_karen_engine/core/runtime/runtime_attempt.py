from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AttemptStatus = Literal["success", "failed", "skipped"]
ExecutionLayer = Literal["core", "provider", "extension", "emergency"]


@dataclass(frozen=True, slots=True)
class RuntimeAttempt:
    target: str
    status: AttemptStatus
    execution_layer: ExecutionLayer

    runtime_engine: str | None = None
    provider_id: str | None = None
    extension_id: str | None = None
    compatibility_profile: str | None = None

    requested_model: str | None = None
    actual_model: str | None = None

    error_type: str | None = None
    error_message: str | None = None

    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
