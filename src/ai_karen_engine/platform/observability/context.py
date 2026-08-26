from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CorrelationContext:
    """Canonical request-scoped correlation and identity context.

    One inbound request maps to exactly one correlation lineage. Nested
    provider/tool/plugin/workflow executions inherit it through contextvars;
    partial identity updates are merged, never replaced wholesale.
    """

    request_id: str | None = None
    correlation_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
        }


_CTX: contextvars.ContextVar[CorrelationContext | None] = contextvars.ContextVar(
    "platform_observability_context", default=None
)


def get_correlation_context() -> CorrelationContext:
    """Return the current request-scoped correlation context."""
    ctx = _CTX.get()
    if ctx is None:
        return CorrelationContext()
    return ctx


def set_correlation_context(context: CorrelationContext) -> contextvars.Token:
    """Replace the current correlation context and return a reset token."""
    return _CTX.set(context)


def bind_correlation_context(**kwargs: Any) -> None:
    """Merge new identity fields into the current context immutably.

    Only overrides fields that are explicitly supplied; existing values are
    preserved so identity resolved earlier in the request is not lost.
    """
    ctx = get_correlation_context()
    updated = CorrelationContext(
        request_id=kwargs.get("request_id", ctx.request_id),
        correlation_id=kwargs.get("correlation_id", ctx.correlation_id),
        tenant_id=kwargs.get("tenant_id", ctx.tenant_id),
        user_id=kwargs.get("user_id", ctx.user_id),
        session_id=kwargs.get("session_id", ctx.session_id),
        conversation_id=kwargs.get("conversation_id", ctx.conversation_id),
    )
    _CTX.set(updated)


def reset_correlation_context(token: contextvars.Token) -> None:
    """Reset the context to its previous value using a token."""
    _CTX.reset(token)


def clear_correlation_context() -> None:
    """Reset the correlation context to empty (e.g. between requests)."""
    _CTX.set(CorrelationContext())
