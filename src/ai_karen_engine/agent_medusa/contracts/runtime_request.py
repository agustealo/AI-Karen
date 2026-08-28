from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class RuntimeRequest:
    """Incoming request for the Agent Medusa runtime."""

    query: str
    session_id: str
    request_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None
    correlation_id: Optional[str] = None
    tenant_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Optional overrides for orchestration.
    priority: str = "medium"
    max_iterations: int = 10
    timeout_seconds: float = 60.0

    # Pre-built authorized inputs from CORTEX/RuntimePolicy.
    authorized_plan: Optional[Dict[str, Any]] = None
    execution_requirements: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
            "max_iterations": self.max_iterations,
            "timeout_seconds": self.timeout_seconds,
            "authorized_plan": self.authorized_plan,
            "execution_requirements": self.execution_requirements,
        }
