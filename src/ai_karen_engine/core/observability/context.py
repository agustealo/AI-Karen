from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ObservabilityContext:
    """Canonical correlation and identity context for observability.

    Every runtime event inherits from this context. It is propagated via
    contextvars so it remains immutable across async boundaries.
    """

    correlation_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
        }
        return {k: v for k, v in data.items() if v is not None}


_CTX: contextvars.ContextVar[ObservabilityContext] = contextvars.ContextVar(
    "observability_context", default=ObservabilityContext()
)


def get_observability_context() -> ObservabilityContext:
    """Return the current observability context."""
    return _CTX.get()


def set_observability_context(context: ObservabilityContext) -> contextvars.Token:
    """Set the current observability context and return a reset token."""
    return _CTX.set(context)


def bind_observability_context(**kwargs: Any) -> None:
    """Update the current context with new values immutably."""
    ctx = get_observability_context()
    updated = ObservabilityContext(
        correlation_id=kwargs.get("correlation_id", ctx.correlation_id),
        request_id=kwargs.get("request_id", ctx.request_id),
        trace_id=kwargs.get("trace_id", ctx.trace_id),
        span_id=kwargs.get("span_id", ctx.span_id),
        user_id=kwargs.get("user_id", ctx.user_id),
        tenant_id=kwargs.get("tenant_id", ctx.tenant_id),
        session_id=kwargs.get("session_id", ctx.session_id),
        conversation_id=kwargs.get("conversation_id", ctx.conversation_id),
    )
    _CTX.set(updated)


def clear_observability_context() -> None:
    """Reset the observability context to empty."""
    _CTX.set(ObservabilityContext())
