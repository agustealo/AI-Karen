"""Execution context handed to a specialist at run time.

Carries the authorization + identity needed for canonical routing:
- ActionExecutionGate checks authorized_plan
- GenerationBridge tags GenerationRequest with policy_decision_id
- ToolBridge emits audit records with tenant/user/trajectory/agent/step ids
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

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
    session_id: Optional[str] = None
    # Trusted transport preferences are validated against the canonical
    # provider registry before construction of a Deep Agents model.
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    # Advisory Intelligence snapshot computed at the canonical Runtime
    # boundary. Not a user-supplied model choice or permission grant.
    learning_task_type: Optional[str] = None
    learned_model_signals: Optional[Any] = None
    # PromptRuntime assembled this from already-authorized NeuroRecall
    # evidence. Never source it directly from an agent/user-supplied task.
    approved_prompt_messages: Optional[list[dict[str, str]]] = None
    learning_context_status: Optional[dict[str, Any]] = None
