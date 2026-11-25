from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from .errors import PrivateEvidenceAuthorizationError

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
    # In-process model text delivery only. Never store a callable in metadata,
    # serialize it, or accept it from an HTTP/client-supplied request.
    token_sink: Callable[[str], Awaitable[None]] | None = field(
        default=None, repr=False, compare=False,
    )
    # Trusted in-process budget guard for every additional actual engine
    # invocation after the Runtime has already charged the initial model call.
    # Never persist, serialize, or populate this from an HTTP client request.
    reserve_additional_model_call: Callable[[], Awaitable[bool]] | None = field(
        default=None, repr=False, compare=False,
    )
    # RuntimePolicy-bound external provider approval is never serialized or
    # accepted from request metadata. Missing approval is denied when the
    # installation requires privileged external execution.
    authorize_external_engine_attempt: Callable[[], Awaitable[bool]] | None = field(
        default=None, repr=False, compare=False,
    )
    # Tracked by the canonical gateway to prohibit switching models after a
    # partial response has already been made visible to the consumer.
    stream_started: bool = field(default=False, repr=False, compare=False)
    # Host-only restriction for private evidence; never derived from client metadata.
    local_only: bool = False
    # Host-only live authorization; never populated from request metadata.
    authorize_private_evidence_attempt: Callable[[], Awaitable[bool]] | None = field(
        default=None, repr=False, compare=False,
    )

    async def require_private_evidence_authorization(self) -> None:
        if not self.local_only:
            return
        try:
            authorized = (
                await self.authorize_private_evidence_attempt()
                if self.authorize_private_evidence_attempt is not None else False
            )
        except Exception:
            raise PrivateEvidenceAuthorizationError("attachment_session_denied") from None
        if authorized is not True:
            raise PrivateEvidenceAuthorizationError("attachment_session_denied")

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
