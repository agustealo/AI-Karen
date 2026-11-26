from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionOutcome,
    ExecutionStatus,
    SpecialistParticipationPhase,
    SpecialistParticipationReceipt,
    UserFeedbackType,
    UserOutcome,
)
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore, OutcomeStoreError
from ai_karen_engine.platform.observability.context import (
    get_correlation_context as get_observability_context,
)

if TYPE_CHECKING:
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import (
        AuthorizedExecutionPlan,
        ExecutionBudgetMeter,
    )

logger = logging.getLogger(__name__)


class OutcomeRecorder:
    """Records execution and user outcome facts linked to trajectories.

    This component remains observational. It does not calculate rewards or
    change runtime behavior. Persistence failures are surfaced in returned
    metadata and structured logs rather than silently swallowed.
    """

    def __init__(self, store: OutcomeStore | None = None) -> None:
        self._store = store

    def _persist(self, payload: dict[str, Any]) -> None:
        if self._store is None:
            payload["outcome_store_status"] = "not_configured"
            return
        try:
            self._store.save_outcome(payload)
            payload["outcome_store_status"] = "stored"
        except Exception:
            payload["outcome_store_status"] = "failed"
            payload["outcome_store_error_code"] = "outcome_persistence_failed"
            logger.exception(
                "outcome.recorder.persistence_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": payload.get("tenant_id"),
                    "user_id": payload.get("user_id"),
                    "source": payload.get("source"),
                },
            )

    async def _persist_async(self, payload: dict[str, Any]) -> None:
        if self._store is None:
            payload["outcome_store_status"] = "not_configured"
            return
        try:
            await self._store.save_outcome_async(payload)
            payload["outcome_store_status"] = "stored"
        except Exception:
            payload["outcome_store_status"] = "failed"
            payload["outcome_store_error_code"] = "outcome_persistence_failed"
            logger.exception(
                "outcome.recorder.async_persistence_failed",
                extra={
                    "outcome_id": payload.get("outcome_id"),
                    "tenant_id": payload.get("tenant_id"),
                    "user_id": payload.get("user_id"),
                    "source": payload.get("source"),
                },
            )

    def _execution_payload(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        status: ExecutionStatus = ExecutionStatus.FAILURE,
        latency_ms: float | None = None,
        provider_errors: list[str] | None = None,
        fallback_count: int = 0,
        tool_success: bool | None = None,
        plugin_success: bool | None = None,
        schema_valid: bool | None = None,
        response_completed: bool | None = None,
        persistence_success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = get_observability_context()
        execution = ExecutionOutcome(
            status=status,
            latency_ms=latency_ms,
            provider_errors=provider_errors or [],
            fallback_count=fallback_count,
            tool_success=tool_success,
            plugin_success=plugin_success,
            schema_valid=schema_valid,
            response_completed=response_completed,
            persistence_success=persistence_success,
        )
        payload = execution.to_dict()
        payload.update(
            {
                "outcome_id": f"out_{uuid.uuid4().hex}",
                "trajectory_id": trajectory_id,
                "decision_observation_id": decision_observation_id,
                "request_id": ctx.request_id,
                "correlation_id": ctx.correlation_id,
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "conversation_id": ctx.conversation_id,
                "recorded_at": datetime.now(timezone.utc),
                "source": "runtime.execution",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        return payload

    def record_execution_outcome(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        status: ExecutionStatus = ExecutionStatus.FAILURE,
        latency_ms: float | None = None,
        provider_errors: list[str] | None = None,
        fallback_count: int = 0,
        tool_success: bool | None = None,
        plugin_success: bool | None = None,
        schema_valid: bool | None = None,
        response_completed: bool | None = None,
        persistence_success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._execution_payload(
            trajectory_id,
            decision_observation_id=decision_observation_id,
            status=status,
            latency_ms=latency_ms,
            provider_errors=provider_errors,
            fallback_count=fallback_count,
            tool_success=tool_success,
            plugin_success=plugin_success,
            schema_valid=schema_valid,
            response_completed=response_completed,
            persistence_success=persistence_success,
            metadata=metadata,
        )
        self._persist(payload)
        return payload

    async def record_execution_outcome_async(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        status: ExecutionStatus = ExecutionStatus.FAILURE,
        latency_ms: float | None = None,
        provider_errors: list[str] | None = None,
        fallback_count: int = 0,
        tool_success: bool | None = None,
        plugin_success: bool | None = None,
        schema_valid: bool | None = None,
        response_completed: bool | None = None,
        persistence_success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._execution_payload(
            trajectory_id,
            decision_observation_id=decision_observation_id,
            status=status,
            latency_ms=latency_ms,
            provider_errors=provider_errors,
            fallback_count=fallback_count,
            tool_success=tool_success,
            plugin_success=plugin_success,
            schema_valid=schema_valid,
            response_completed=response_completed,
            persistence_success=persistence_success,
            metadata=metadata,
        )
        await self._persist_async(payload)
        return payload

    async def record_specialist_participation_async(
        self,
        *,
        context: ChatExecutionContext,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        step_id: str,
        specialist_id: str,
        phase: SpecialistParticipationPhase,
    ) -> SpecialistParticipationReceipt:
        """Append an admitted specialist observation, not a task outcome.

        The coordinator owns phase and step provenance. This boundary requires
        the original authenticated runtime authority, not serialized grants.
        A receipt is returned only after the strict append has completed.
        """
        from ai_karen_engine.core.runtime.chat_runtime_contract import (
            ChatExecutionContext,
        )
        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan,
            ExecutionBudgetMeter,
        )

        if (
            not isinstance(context, ChatExecutionContext)
            or not isinstance(plan, AuthorizedExecutionPlan)
            or not isinstance(meter, ExecutionBudgetMeter)
        ):
            raise PermissionError("specialist_participation_authority_invalid")
        context.require_authenticated_user()
        # A scheduler skip observes non-invocation under the already admitted
        # parent plan. It must not register a new executable child grant just
        # to record why an allowed specialist was not invoked.
        specialist_allowed = (
            specialist_id in plan.allowed_agents
            if phase is SpecialistParticipationPhase.SKIPPED
            else list(plan.allowed_agents) == [specialist_id]
        )
        if (
            not context.is_runtime_model_plan_authorized(plan, meter)
            or not specialist_allowed
        ):
            raise PermissionError("specialist_participation_authority_invalid")
        if self._store is None:
            raise OutcomeStoreError("Specialist participation persistence unavailable")
        receipt = SpecialistParticipationReceipt(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            trajectory_id=context.request_id,
            correlation_id=context.correlation_id,
            step_id=step_id,
            specialist_id=specialist_id,
            phase=phase,
            observed_at=datetime.now(timezone.utc),
        )
        await self._store.save_unique_outcome_async(receipt.to_evidence_payload())
        return receipt

    async def record_governed_tool_outcome_async(
        self,
        *,
        tool_call_id: str,
        trajectory_id: str,
        correlation_id: str,
        session_id: str | None,
        tenant_id: str,
        user_id: str,
        policy_decision_id: str,
        tool_name: str,
        tool_version: str | None,
        agent_id: str,
        step_id: str,
        success: bool,
        error_type: str | None = None,
        result_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Durably record a governed bridge observation, never model testimony.

        Unlike conversational outcomes, this cannot use the best-effort
        _persist_async adapter: losing an audit receipt must be visible to
        callers and must not be reported as a proven tool execution.
        """
        if self._store is None:
            from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

            raise OutcomeStoreError("Governed tool outcome persistence unavailable")
        if not all((
            tool_call_id, trajectory_id, correlation_id, tenant_id, user_id,
            policy_decision_id, tool_name, agent_id, step_id,
        )):
            raise ValueError("Complete governed tool execution identity required")
        payload: dict[str, Any] = {
            "outcome_id": f"out_tool_{tool_call_id.replace('-', '')}",
            "source": "runtime.execution",
            "trajectory_id": trajectory_id,
            "request_id": tool_call_id,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "recorded_at": datetime.now(timezone.utc),
            **ExecutionOutcome(
                status=ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILURE,
                tool_success=success,
                response_completed=False,
            ).to_dict(),
            "metadata": {
                "event_type": "agent.tool.execution",
                "receipt_version": "governed-tool.v1",
                "execution_scope": "tool_runtime_acknowledgment",
                "independently_verified": False,
                "tool_call_id": tool_call_id,
                "policy_decision_id": policy_decision_id,
                "tool_name": tool_name,
                "tool_version": tool_version,
                "agent_id": agent_id,
                "step_id": step_id,
                "error_type": error_type,
                "result_sha256": result_sha256,
            },
        }
        await self._store.save_unique_outcome_async(payload)
        return payload

    def record_user_outcome(
        self,
        trajectory_id: str | None = None,
        *,
        decision_observation_id: str | None = None,
        feedback_type: UserFeedbackType | None = None,
        rating: float | None = None,
        correction_text: str | None = None,
        confidence: float | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = get_observability_context()
        user = UserOutcome(
            feedback_type=feedback_type,
            rating=rating,
            correction_text=correction_text,
            confidence=confidence,
        )
        payload = user.to_dict()
        payload.update(
            {
                "outcome_id": f"out_{uuid.uuid4().hex}",
                "trajectory_id": trajectory_id,
                "decision_observation_id": decision_observation_id,
                "request_id": ctx.request_id,
                "correlation_id": ctx.correlation_id,
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "conversation_id": ctx.conversation_id,
                "message_id": message_id,
                "recorded_at": datetime.now(timezone.utc),
                "source": "user.feedback",
            }
        )
        if metadata:
            payload["metadata"] = metadata
        self._persist(payload)
        return payload
