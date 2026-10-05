import logging
from typing import Dict, List, Optional, Any
from uuid import uuid4
from datetime import datetime, timezone
from ..contracts.trace import AgentTrace
from ..contracts.events import AgentEvent, AgentEventType

logger = logging.getLogger(__name__)

class MedusaTracer:
    """Execution tracer for AgentMedusa."""
    
    def __init__(self):
        self._active_traces: Dict[str, AgentTrace] = {}
        self._trace_history: List[AgentTrace] = []
        self._max_history = 100

    def start_trace(self, agent_id: str, correlation_id: Optional[str] = None) -> AgentTrace:
        """Start a new execution trace."""
        trace_id = str(uuid4())
        trace = AgentTrace(
            trace_id=trace_id,
            agent_id=agent_id,
            metadata={"correlation_id": correlation_id} if correlation_id else {}
        )
        self._active_traces[trace_id] = trace
        
        # Add start event
        self.add_event(trace_id, AgentEventType.AGENT_STARTED, f"Agent {agent_id} started execution")
        
        return trace

    def add_event(self, trace_id: str, event_type: AgentEventType, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Add an event to an active trace."""
        if trace_id not in self._active_traces:
            logger.warning(f"Attempted to add event to non-existent trace: {trace_id}")
            return
        
        trace = self._active_traces[trace_id]
        event = AgentEvent(
            type=event_type,
            agent_id=trace.agent_id,
            message=message,
            metadata=metadata or {},
            correlation_id=trace.metadata.get("correlation_id")
        )
        trace.add_event(event)

    def end_trace(self, trace_id: str, success: bool = True):
        """End an active trace and move to history."""
        if trace_id not in self._active_traces:
            return
        
        trace = self._active_traces.pop(trace_id)

        status_msg = "completed successfully" if success else "failed"
        trace.add_event(
            AgentEvent(
                type=(
                    AgentEventType.AGENT_COMPLETED
                    if success
                    else AgentEventType.AGENT_FAILED
                ),
                agent_id=trace.agent_id,
                message=f"Agent {trace.agent_id} {status_msg}",
                metadata={},
                correlation_id=trace.metadata.get("correlation_id"),
            )
        )
        trace.complete()

        self._trace_history.append(trace)
        if len(self._trace_history) > self._max_history:
            self._trace_history.pop(0)
            
        return trace

    def get_trace(self, trace_id: str) -> Optional[AgentTrace]:
        """Get a trace by ID (active or historical)."""
        if trace_id in self._active_traces:
            return self._active_traces[trace_id]
        for trace in self._trace_history:
            if trace.trace_id == trace_id:
                return trace
        return None

_tracer: Optional[MedusaTracer] = None

def get_medusa_tracer() -> MedusaTracer:
    global _tracer
    if _tracer is None:
        _tracer = MedusaTracer()
    return _tracer
