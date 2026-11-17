"""Recovering an HTTP reply must not bypass durable transcript authority."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
    PersonaExecutionSnapshot,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    TranscriptPersistenceResult,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted", [True, False])
async def test_recovery_response_requires_durable_transcript(persisted):
    from contextlib import ExitStack

    runtime = object.__new__(ChatRuntime)
    runtime._emitter = MagicMock()
    runtime._trajectory_recorder = MagicMock()
    runtime._trajectory_recorder.start.return_value.trajectory_id = "trace-1"
    ctx = ChatExecutionContext(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="session-a",
        conversation_id="22222222-2222-2222-2222-222222222222",
        request_id="request-a",
        correlation_id="correlation-a",
    )
    # Recovery is a real authenticated runtime path. The fixture must not
    # bypass the original-principal requirement added for model admission.
    ctx.authenticated_user = UserData(
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        roles=["user"],
        permissions=[],
        is_active=True,
        is_verified=True,
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        context=ctx,
    )
    snapshot = PersonaExecutionSnapshot(
        user_id=ctx.user_id, tenant_id=ctx.tenant_id, status="none",
    )
    decision = ExecutionDecision(max_model_calls=2, memory_write_allowed=True)
    plan = AuthorizedExecutionPlan(
        execution_id="exec-request-a",
        policy_decision_id="policy-a",
        authorized_user_id=ctx.user_id,
        authorized_tenant_id=ctx.tenant_id,
        authorized_session_id=ctx.session_id,
        budget=ExecutionBudget(max_model_calls=2),
    )
    recovered = ChatExecutionResult(
        answer="Recovered model-generated answer.",
        status=ChatExecutionStatus.DEGRADED,
        metadata=ChatRuntimeMetadata(
            correlation_id=ctx.correlation_id,
            actual_provider="ollama-local",
            actual_model="local-model",
            response_source="model",
            degraded_mode=True,
            fallback_level=1,
        ),
    )
    transcript = TranscriptPersistenceResult(
        status="persisted" if persisted else "failed",
        conversation_id=ctx.conversation_id,
        assistant_message_id="message-a" if persisted else None,
        persisted_messages=2 if persisted else 0,
    )
    with ExitStack() as stack:
        for name in (
            "_bind_observability_context", "_apply_selected_model_settings",
        ):
            stack.enter_context(patch.object(runtime, name))
        for name in (
            "_prepare_conversation_continuation",
            "_record_user_behavior_observation",
            "_record_trajectory_completion", "_record_execution_outcome",
        ):
            stack.enter_context(patch.object(runtime, name, new_callable=AsyncMock))
        # A default AsyncMock is truthy and represents an actual runtime gate.
        # The scenario must explicitly authorize admission and avoid approval.
        stack.enter_context(patch.object(
            runtime, "_resolve_gate", new_callable=AsyncMock, return_value=None,
        ))
        stack.enter_context(patch.object(
            runtime, "_resolve_human_approval_gate",
            new_callable=AsyncMock, return_value=None,
        ))
        stack.enter_context(patch.object(
            runtime, "_freeze_persona_snapshot",
            new_callable=AsyncMock, return_value=snapshot,
        ))
        stack.enter_context(patch.object(
            runtime, "_decide", new_callable=AsyncMock, return_value=decision,
        ))
        stack.enter_context(patch.object(
            runtime, "_record_learning_decision",
            new_callable=AsyncMock, return_value="observation-1",
        ))
        stack.enter_context(patch.object(runtime, "_build_authorized_plan", return_value=plan))
        stack.enter_context(patch.object(runtime, "_grounded_personal_response", return_value=None))
        stack.enter_context(patch.object(runtime, "_should_execute_authorized_reasoning", return_value=False))
        stack.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_direct_capability_executor",
            return_value=SimpleNamespace(can_handle=lambda _decision: False),
        ))
        stack.enter_context(patch.object(
            runtime, "_run_simple", new_callable=AsyncMock,
            side_effect=RuntimeError("primary failed"),
        ))
        fallback = stack.enter_context(patch(
            "ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback",
            new_callable=AsyncMock, return_value=recovered,
        ))
        transcript_write = stack.enter_context(patch.object(
            runtime, "_persist_transcript",
            new_callable=AsyncMock, return_value=transcript,
        ))
        memory = stack.enter_context(patch.object(
            runtime, "_persist_memory", new_callable=AsyncMock,
        ))
        result = await runtime.execute(request)

    assert fallback.await_args.kwargs["authorized_plan"] is plan
    assert fallback.await_args.kwargs["meter"].budget is plan.budget
    transcript_write.assert_awaited_once()
    assert transcript_write.await_args.args[1] == "Recovered model-generated answer."
    assert result.metadata.extra["transcript_persistence_status"] == transcript.status
    if persisted:
        assert result.status == ChatExecutionStatus.DEGRADED
        assert result.answer == "Recovered model-generated answer."
        memory.assert_awaited_once()
    else:
        assert result.status == ChatExecutionStatus.ERROR
        assert result.answer == ""
        assert result.metadata.extra["error_code"] == "CHAT_TRANSCRIPT_PERSISTENCE_FAILED"
        memory.assert_not_awaited()
