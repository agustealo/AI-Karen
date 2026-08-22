from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_karen_engine.core.observability.emitter import ObservabilitySink


def create_audit_sink(get_audit: Callable[[], Any] | None = None) -> ObservabilitySink:
    """Create a sink that emits selected observability events to audit storage.

    Audit records must always be redacted and must include correlation
    identifiers so they can be joined with logs and traces.
    """
    try:
        if get_audit is None:
            try:
                from ai_karen_engine.audit import PerformanceAuditor

                auditor = PerformanceAuditor()

                def _emit(payload: dict[str, Any]) -> None:
                    try:
                        auditor.record(payload)
                    except Exception:
                        pass

            except Exception:

                def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
                    pass

        else:
            auditor = get_audit()

            def _emit(payload: dict[str, Any]) -> None:
                try:
                    auditor.record(payload)
                except Exception:
                    pass

    except Exception:

        def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
            pass

    return ObservabilitySink(name="audit", emit=_emit, redact=True)
