from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from .events import AgentEvent

@dataclass
class AgentTrace:
    """Represents a full execution trace of an agent"""
    trace_id: str
    agent_id: str
    events: List[AgentEvent] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_ms(self) -> Optional[float]:
        if not self.end_time:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000.0

    def add_event(self, event: AgentEvent) -> None:
        self.events.append(event)
        
    def complete(self) -> None:
        self.end_time = datetime.now(timezone.utc)


@dataclass
class ExecutionTrajectory:
    """Multi-agent execution trajectory for one request (A25).

    Aggregates per-step results and the full AgentEvent stream so a run is
    reproducible and traceable. Sinks into observability/outcome later.
    """
    request_id: str
    trajectory_id: str
    events: List[AgentEvent] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "running"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_event(self, event: AgentEvent) -> None:
        self.events.append(event)

    def record_step(self, step: Dict[str, Any]) -> None:
        self.steps.append(step)

    def complete(self, status: str) -> None:
        self.status = status
        self.completed_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trajectory_id": self.trajectory_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "steps": self.steps,
            "event_count": len(self.events),
            "metadata": self.metadata,
        }
