from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_karen_engine.core.observability.emitter import ObservabilitySink


def create_logging_sink(get_logger: Callable[[str], Any] | None = None) -> ObservabilitySink:
    """Create a sink that emits observability events as structured log records."""
    try:
        if get_logger is None:
            from ai_karen_engine.core.logging.logger import get_logger as _get_logger
            get_logger = _get_logger
        logger = get_logger("ai_karen_engine.core.observability.sinks.logging")

        def _emit(payload: dict[str, Any]) -> None:
            logger.info("observability.event", extra=payload)

    except Exception:
        def _emit(payload: dict[str, Any]) -> None:  # type: ignore[misc]
            print(payload)

    return ObservabilitySink(name="structured_log", emit=_emit, redact=True)
