"""Execution context handed to a specialist at run time.

Carries the authorization + identity needed for canonical routing:
- ActionExecutionGate checks authorized_plan
- GenerationBridge tags GenerationRequest with policy_decision_id
- ToolBridge emits audit records with tenant/user/trajectory/agent/step ids
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from ...core.runtime.chat_runtime_contract import ChatExecutionContext

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
    # Original authenticated ingress context, never reconstructed from agent IDs.
    authenticated_chat_context: Optional["ChatExecutionContext"] = None
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

    # Coordinator-owned, in-process observation only. Never supplied from
    # serialized request data, a prompt, or a specialist result.
    _invocation_entry: Optional[Callable[[], Awaitable[None]]] = field(
        default=None, repr=False, compare=False,
    )

    async def acknowledge_invocation_entry(self) -> None:
        """Record entry into the trusted run method, not model/tool activity."""
        if self._invocation_entry is not None:
            await self._invocation_entry()
