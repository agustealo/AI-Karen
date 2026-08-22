"""Canonical model lifecycle event contract.

Defines the stable vocabulary for model-lifecycle observability. A pluggable
emitter hook lets the canonical observability spine (OBS-3A) consume these events
without this module depending on it. Until an emitter is registered, events are
no-ops (debug-logged only) so the contract is safe to emit from hot paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

CANONICAL_LIFECYCLE_EVENTS = (
    "model.discovered",
    "model.available",
    "model.unavailable",
    "model.load_started",
    "model.loaded",
    "model.load_failed",
    "model.evicted",
    "model.download_started",
    "model.download_failed",
    "model.download.requested",
    "model.download.started",
    "model.download.completed",
    "model.load.started",
    "model.load.completed",
    "model.unloaded",
    "model.health.changed",
)


class ModelLifecycleState(str, Enum):
    """Canonical model lifecycle states."""

    KNOWN = "KNOWN"
    DISCOVERED = "DISCOVERED"
    REMOTE_AVAILABLE = "REMOTE_AVAILABLE"
    DOWNLOADING = "DOWNLOADING"
    INSTALLED = "INSTALLED"
    LOADABLE = "LOADABLE"
    LOADING = "LOADING"
    LOADED = "LOADED"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNAVAILABLE = "UNAVAILABLE"
    REMOVED = "REMOVED"


class ModelLifecycleEvent(str, Enum):
    """Canonical model lifecycle events emitted by the runtime."""

    MODEL_DISCOVERED = "model.discovered"
    MODEL_AVAILABLE = "model.available"
    MODEL_UNAVAILABLE = "model.unavailable"
    MODEL_LOAD_STARTED = "model.load_started"
    MODEL_LOADED = "model.loaded"
    MODEL_LOAD_FAILED = "model.load_failed"
    MODEL_EVICTED = "model.evicted"
    MODEL_DOWNLOAD_STARTED = "model.download_started"
    MODEL_DOWNLOAD_FAILED = "model.download_failed"
    MODEL_DOWNLOAD_REQUESTED = "model.download.requested"
    MODEL_DOWNLOAD_STARTED_DOT = "model.download.started"
    MODEL_DOWNLOAD_COMPLETED = "model.download.completed"
    MODEL_LOAD_STARTED_DOT = "model.load.started"
    MODEL_LOAD_COMPLETED = "model.load.completed"
    MODEL_UNLOADED = "model.unloaded"
    MODEL_HEALTH_CHANGED = "model.health.changed"


@dataclass
class ModelLifecycleRecord:
    """Structured payload for a model lifecycle event.

    Fields map 1:1 to the observability metadata envelope; never carries secrets,
    prompts, or raw model bytes.
    """

    event: ModelLifecycleEvent
    model_id: str
    provider: str = ""
    runtime_engine: str = ""
    correlation_id: Optional[str] = None
    duration_ms: Optional[float] = None
    error_code: Optional[str] = None
    status: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "event": self.event.value,
            "model_id": self.model_id,
            "provider": self.provider,
            "runtime_engine": self.runtime_engine,
            "correlation_id": self.correlation_id,
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        if self.status is not None:
            payload["status"] = self.status
        if self.extra:
            payload.update(self.extra)
        return payload


_Emitter = Callable[[ModelLifecycleRecord], None]
_emitter: Optional[_Emitter] = None


def register_model_lifecycle_emitter(emitter: Optional[_Emitter]) -> None:
    """Install the canonical observability emitter (wired by the observability spine)."""
    global _emitter
    _emitter = emitter


def emit_model_lifecycle_event(
    event: ModelLifecycleEvent,
    *,
    model_id: str,
    provider: str = "",
    runtime_engine: str = "",
    correlation_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    error_code: Optional[str] = None,
    status: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emit a canonical model lifecycle event.

    No-op until an emitter is registered via ``register_model_lifecycle_emitter``.
    An emitter error is logged and swallowed so it can never break the hot path.
    """
    record = ModelLifecycleRecord(
        event=event,
        model_id=model_id,
        provider=provider,
        runtime_engine=runtime_engine,
        correlation_id=correlation_id,
        duration_ms=duration_ms,
        error_code=error_code,
        status=status,
        extra=dict(extra) if extra else {},
    )
    installed = _emitter
    if installed is None:
        logger.debug("model lifecycle event (no emitter): %s", record.to_dict())
        return
    try:
        installed(record)
    except Exception:  # pragma: no cover - emitter must never break the runtime
        logger.debug("model lifecycle emitter failed: %s", record.to_dict(), exc_info=True)
