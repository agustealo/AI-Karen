from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from enum import Enum

class AgentEventType(str, Enum):
    """Types of events in the agent system"""
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    REASONING_STEP = "reasoning_step"
    MEMORY_RECALL = "memory_recall"
    MEMORY_PERSIST = "memory_persist"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    CHECKPOINT_PERSISTED = "checkpoint_persisted"

@dataclass
class AgentEvent:
    """Represents an event in the agent execution lifecycle"""
    type: AgentEventType
    agent_id: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
