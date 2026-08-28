from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class RuntimeRequest:
    """Incoming request for the Agent Medusa runtime.

    Governed execution must carry an explicit tenant scope. A legacy caller may
    provide that scope in ``context['tenant_id']`` while it migrates to the typed
    field, but Medusa never invents a default tenant.
    """

    query: str
    session_id: str
    request_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Optional overrides for orchestration
    priority: str = "medium"  # low, medium, high, critical
    max_iterations: int = 10
    timeout_seconds: float = 60.0

    # Pre-built authorized inputs from CORTEX/RuntimePolicy
    authorized_plan: Optional[Dict[str, Any]] = None
    execution_requirements: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        tenant_id = self.tenant_id
        if tenant_id is None:
            context_tenant_id = self.context.get("tenant_id")
            tenant_id = str(context_tenant_id).strip() if context_tenant_id else ""
        else:
            tenant_id = str(tenant_id).strip()

        if not tenant_id:
            raise ValueError("Agent Medusa RuntimeRequest requires tenant_id")
        self.tenant_id = tenant_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
            "max_iterations": self.max_iterations,
            "timeout_seconds": self.timeout_seconds,
            "authorized_plan": self.authorized_plan,
            "execution_requirements": self.execution_requirements,
        }
