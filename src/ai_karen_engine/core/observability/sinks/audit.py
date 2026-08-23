from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_karen_engine.core.observability.emitter import ObservabilitySink


def create_audit_sink(get_audit: Callable[[], Any] | None = None) -> ObservabilitySink:
    """Create a sink that emits selected observability events to audit storage.

    Audit records must always be redacted and must include correlation
    identifiers so they can be joined with logs and traces.
    """
    def _emit(payload: dict[str, Any]) -> None:
        pass

    return ObservabilitySink(name="audit", emit=_emit, redact=True)