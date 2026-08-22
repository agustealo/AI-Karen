from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from datetime import datetime
from enum import Enum

class ResponseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    DEGRADED = "degraded"

@dataclass
class ArtifactRef:
    """Reference to a non-text execution artifact (A23).

    Agents may produce more than text (files, code, tables, reports, images,
    citations, tool results, structured data). The UI contract carries these
    as references rather than flattening everything into content: str.
    """
    artifact_id: str
    kind: str  # file, code, table, report, image, citation, tool_result, structured
    ref: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RuntimeResponse:
    """Standard response from the AgentMedusa runtime"""
    request_id: str
    status: ResponseStatus
    content: str
    intermediate_steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    execution_time_ms: float = 0.0

    # Trace of which agents were involved
    agent_trace: List[str] = field(default_factory=list)
    artifacts: List[ArtifactRef] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "content": self.content,
            "intermediate_steps": self.intermediate_steps,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "execution_time_ms": self.execution_time_ms,
            "agent_trace": self.agent_trace,
            "artifacts": [a.__dict__ for a in self.artifacts],
        }
