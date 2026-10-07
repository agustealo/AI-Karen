from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

@dataclass(slots=True)
class ExpressionTask:
    task_id: str
    kind: str
    messages: list[dict[str, Any]]
    response_mode: str
    required_capabilities: list[str]
    forbidden_capabilities: list[str]
    preferred_provider: str | None = None
    preferred_model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout_ms: int = 30000
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class ExpressionResult:
    task_id: str
    text: str
    provider: str | None
    model: str | None
    engine_id: str
    engine_mode: str
    runtime_engine: str | None
    response_source: str
    attempts: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    latency_ms: float
    degraded: bool = False
    degradation_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class EngineHealth:
    engine_id: str
    status: Literal['healthy','degraded','unavailable','disabled']
    capabilities: list[str]
    models: list[str]
    latency_ms: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
