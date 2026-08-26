"""
Observability hooks for PromptRuntime.

Emits structured events for prompt assembly lifecycle tracking.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PromptEventType(str, Enum):
    """Types of prompt assembly events."""
    RESOLVE_STARTED = "prompt.resolve.started"
    RESOLVE_COMPLETED = "prompt.resolve.completed"
    RESOLVE_FAILED = "prompt.resolve.failed"
    ASSEMBLY_STARTED = "prompt.assembly.started"
    SECTION_INCLUDED = "prompt.section.included"
    SECTION_TRUNCATED = "prompt.section.truncated"
    OVERRIDE_REJECTED = "prompt.override.rejected"
    ASSEMBLY_COMPLETED = "prompt.assembly.completed"
    ASSEMBLY_FAILED = "prompt.assembly.failed"


@dataclass
class PromptEvent:
    """Structured prompt assembly event."""
    
    event_type: PromptEventType
    correlation_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Event-specific fields
    prompt_id: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    
    # Budget tracking
    token_budget: int = 0
    token_estimate: int = 0
    
    # Component tracking
    memory_count: int = 0
    tool_count: int = 0
    
    # Truncation tracking
    truncation_count: int = 0
    assembly_latency_ms: float = 0.0
    
    # Status
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_type": self.event_type.value,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "token_budget": self.token_budget,
            "token_estimate": self.token_estimate,
            "memory_count": self.memory_count,
            "tool_count": self.tool_count,
            "truncation_count": self.truncation_count,
            "assembly_latency_ms": self.assembly_latency_ms,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class PromptObservability:
    """Observability hooks for prompt assembly lifecycle."""
    
    def __init__(self) -> None:
        self.events: List[PromptEvent] = []
        self._current_correlation_id: Optional[str] = None
        self._assembly_start_time: Optional[float] = None
    
    def start_correlation(self) -> str:
        """Start a new correlation context."""
        self._current_correlation_id = str(uuid.uuid4())[:8]
        return self._current_correlation_id
    
    def emit_event(self, event: PromptEvent) -> None:
        """Emit an event to the observability system."""
        if not self._current_correlation_id:
            self.start_correlation()
        event.correlation_id = self._current_correlation_id
        self.events.append(event)
        
        # Log at appropriate level
        if "failed" in event.event_type.value:
            logger.error(f"Prompt event: {event.event_type.value} - {event.error_message}")
        elif "truncated" in event.event_type.value:
            logger.warning(f"Prompt event: {event.event_type.value}")
        else:
            logger.info(f"Prompt event: {event.event_type.value}")
    
    def emit_resolve_started(self, prompt_id: str, version: str) -> None:
        """Emit resolve started event."""
        event = PromptEvent(
            event_type=PromptEventType.RESOLVE_STARTED,
            prompt_id=prompt_id,
            prompt_version=version,
            status="started",
        )
        self.emit_event(event)
    
    def emit_resolve_completed(self, prompt_id: str, version: str, prompt_hash: str) -> None:
        """Emit resolve completed event."""
        event = PromptEvent(
            event_type=PromptEventType.RESOLVE_COMPLETED,
            prompt_id=prompt_id,
            prompt_version=version,
            prompt_hash=prompt_hash,
            status="completed",
        )
        self.emit_event(event)
    
    def emit_resolve_failed(self, prompt_id: str, version: str, error: str) -> None:
        """Emit resolve failed event."""
        event = PromptEvent(
            event_type=PromptEventType.RESOLVE_FAILED,
            prompt_id=prompt_id,
            prompt_version=version,
            status="failed",
            error_code="resolve_error",
            error_message=error,
        )
        self.emit_event(event)
    
    def emit_assembly_started(self, prompt_id: str, version: str, token_budget: int) -> None:
        """Emit assembly started event."""
        self._assembly_start_time = time.time()
        event = PromptEvent(
            event_type=PromptEventType.ASSEMBLY_STARTED,
            prompt_id=prompt_id,
            prompt_version=version,
            token_budget=token_budget,
            status="started",
        )
        self.emit_event(event)
    
    def emit_assembly_completed(
        self,
        prompt_id: str,
        version: str,
        prompt_hash: str,
        token_estimate: int,
        memory_count: int,
        tool_count: int,
        truncation_count: int,
    ) -> None:
        """Emit assembly completed event."""
        latency_ms = 0.0
        if self._assembly_start_time:
            latency_ms = (time.time() - self._assembly_start_time) * 1000
            self._assembly_start_time = None
        
        event = PromptEvent(
            event_type=PromptEventType.ASSEMBLY_COMPLETED,
            prompt_id=prompt_id,
            prompt_version=version,
            prompt_hash=prompt_hash,
            token_estimate=token_estimate,
            memory_count=memory_count,
            tool_count=tool_count,
            truncation_count=truncation_count,
            assembly_latency_ms=latency_ms,
            status="completed",
        )
        self.emit_event(event)
    
    def emit_assembly_failed(self, prompt_id: str, version: str, error: str) -> None:
        """Emit assembly failed event."""
        latency_ms = 0.0
        if self._assembly_start_time:
            latency_ms = (time.time() - self._assembly_start_time) * 1000
            self._assembly_start_time = None
        
        event = PromptEvent(
            event_type=PromptEventType.ASSEMBLY_FAILED,
            prompt_id=prompt_id,
            prompt_version=version,
            assembly_latency_ms=latency_ms,
            status="failed",
            error_code="assembly_error",
            error_message=error,
        )
        self.emit_event(event)
    
    def emit_override_rejected(self, field: str, reason: str) -> None:
        """Emit override rejected event."""
        event = PromptEvent(
            event_type=PromptEventType.OVERRIDE_REJECTED,
            status="rejected",
            error_code="override_violation",
            error_message=f"Override rejected for field '{field}': {reason}",
            metadata={"field": field, "reason": reason},
        )
        self.emit_event(event)
    
    def clear_events(self) -> None:
        """Clear all events."""
        self.events.clear()
    
    def get_events_by_type(self, event_type: PromptEventType) -> List[PromptEvent]:
        """Get events by type."""
        return [e for e in self.events if e.event_type == event_type]
    
    def get_events_by_correlation(self, correlation_id: str) -> List[PromptEvent]:
        """Get events by correlation ID."""
        return [e for e in self.events if e.correlation_id == correlation_id]


# Global observability instance
_observability: Optional[PromptObservability] = None


def get_observability() -> PromptObservability:
    """Get the global observability instance."""
    global _observability
    if _observability is None:
        _observability = PromptObservability()
    return _observability