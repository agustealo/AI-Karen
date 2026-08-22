"""Execution context handed to a specialist at run time.

Carries the authorization + identity needed for canonical routing:
- ActionExecutionGate checks authorized_plan
- GenerationBridge tags GenerationRequest with policy_decision_id
- ToolBridge emits audit records with tenant/user/trajectory/agent/step ids
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...core.runtime.contracts import AuthorizedExecutionPlan, ExecutionBudgetMeter


@dataclass
class SpecialistExecutionContext:
    authorized_plan: AuthorizedExecutionPlan
    tenant_id: str = "default"
    user_id: str = "anonymous"
    policy_decision_id: str = ""
    trajectory_id: str = ""
    correlation_id: str = ""
    step_id: str = ""
    budget_meter: Optional[Any] = None
    event_emitter: Optional[Any] = None
