"""Adversarial recovery must reuse RuntimePolicy authority and budget."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.expression.errors import EngineUnavailableError
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RiskLevel,
)
from ai_karen_engine.core.runtime.runtime_fallback import build_runtime_fallback


def _authorized_turn():
    context = SimpleNamespace(
        request_id="recovery-request",
        user_id="alice",
        tenant_id="tenant-one",
        session_id="session-one",
    )
    request = SimpleNamespace(
        context=context,
        metadata={"memory_context": {"recall": []}},
        max_tokens=128,
        preferred_provider="ollama-local",
        preferred_model="observed-local-model",
    )
    decision = ExecutionDecision(
        max_model_calls=2,
        policy_decision_id="policy-verified",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-recovery-request",
        policy_decision_id="policy-verified",
        authorized_user_id="alice",
        authorized_tenant_id="tenant-one",
        authorized_session_id="session-one",
        budget=ExecutionBudget(max_model_calls=2, max_duration_ms=30000),
    )
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    return request, decision, plan, meter


async def _attempt(runtime, request, decision, plan, meter, failure=None):
    return await build_runtime_fallback(
        runtime=runtime,
        request=request,
        failure=failure or RuntimeError("provider request failed"),
        correlation_id="correlation-recovery",
        conversation_id="conversation-recovery",
        decision=decision,
        authorized_plan=plan,
        meter=meter,
    )


@pytest.mark.asyncio
async def test_authorized_recovery_uses_exact_original_plan_and_meter():
    request, decision, plan, meter = _authorized_turn()

    class Runtime:
        async def _run_simple(self, request_arg, decision_arg, plan_arg, meter_arg, memory):
            assert request_arg is request
            assert decision_arg is decision
            assert plan_arg is plan
            assert meter_arg is meter
            assert memory == {"memory_context": {"recall": []}}
            assert await meter_arg.consume_model_call()
            return "Observed model recovery.", {
                "actual_provider": "ollama-local",
                "actual_model": "observed-local-model",
                "response_source": "provider_runtime",
                "fallback_level": 0,
            }

    result = await _attempt(Runtime(), request, decision, plan, meter)
    assert result is not None
    assert result.answer == "Observed model recovery."
    assert result.metadata.degraded_mode is True
    assert result.metadata.actual_model == "observed-local-model"
    assert meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_plan", "missing_meter", "zero_decision_budget",
        "zero_plan_budget", "already_used_model_budget",
        "cross_user", "cross_tenant", "cross_session",
        "other_policy", "requires_approval", "human_gate",
        "high_risk", "tool_intent", "plugin_intent",
        "authorized_tool", "authorized_plugin",
        "disallowed_degraded", "different_meter_budget",
        "gateway_exhausted", "permission_denied", "receipt_uncertain",
        "medusa_admission_denied", "medusa_registration_unconfirmed",
        "medusa_registration_conflict", "medusa_durable_registration_conflict",
        "medusa_durable_registration_unconfirmed", "medusa_durable_running_conflict",
        "medusa_durable_running_unconfirmed", "medusa_local_registration_conflict",
    ],
)
async def test_recovery_must_never_invent_execution_authority(case):
    request, decision, plan, meter = _authorized_turn()
    failure = RuntimeError("upstream failed")
    if case == "missing_plan":
        plan = None
    elif case == "missing_meter":
        meter = None
    elif case == "zero_decision_budget":
        decision.max_model_calls = 0
    elif case == "zero_plan_budget":
        plan.budget.max_model_calls = 0
    elif case == "already_used_model_budget":
        assert await meter.consume_model_call()
        assert await meter.consume_model_call()
    elif case == "cross_user":
        plan.authorized_user_id = "bob"
    elif case == "cross_tenant":
        plan.authorized_tenant_id = "tenant-two"
    elif case == "cross_session":
        plan.authorized_session_id = "session-two"
    elif case == "other_policy":
        decision.policy_decision_id = "unrelated-policy"
    elif case == "requires_approval":
        plan.approval_requirements = ["admin_approval"]
    elif case == "human_gate":
        decision.requires_human_gate = True
    elif case == "high_risk":
        decision.risk_level = RiskLevel.HIGH
    elif case == "tool_intent":
        decision.tool_requirements = ["search.weather"]
    elif case == "plugin_intent":
        decision.plugin_candidates = ["telegram"]
    elif case == "authorized_tool":
        plan.allowed_tools = ["search.weather"]
    elif case == "authorized_plugin":
        plan.allowed_plugins = ["telegram"]
    elif case == "disallowed_degraded":
        plan.degraded_allowed = False
    elif case == "different_meter_budget":
        meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=20))
        meter.start()
    elif case == "gateway_exhausted":
        failure = EngineUnavailableError("all_model_engines_failed")
    elif case == "permission_denied":
        failure = PermissionError("not authorized")
    elif case in {
        "medusa_admission_denied",
        "medusa_registration_unconfirmed",
        "medusa_registration_conflict",
    }:
        from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
            DistributedRunAdmissionRejected,
        )

        reason = {
            "medusa_admission_denied": "redis_capacity_reserve_exhausted",
            "medusa_registration_unconfirmed": "redis_registration_unconfirmed",
            "medusa_registration_conflict": "redis_registration_conflict",
        }[case]
        failure = DistributedRunAdmissionRejected(reason)
    elif case.startswith(("medusa_durable_", "medusa_local_")):
        from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected

        failure = ExecutionAdmissionRejected(case)
    elif case == "receipt_uncertain":
        from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

        failure = OutcomeStoreError("receipt acknowledgement uncertain")

    class Runtime:
        async def _run_simple(self, *_args, **_kwargs):
            pytest.fail("Recovery was called without original runtime authority")

    assert await _attempt(Runtime(), request, decision, plan, meter, failure) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "meta",
    [
        {"actual_provider": None, "actual_model": "model", "response_source": "model"},
        {"actual_provider": "ollama-local", "actual_model": None, "response_source": "model"},
        {"actual_provider": "ollama-local", "actual_model": "model", "response_source": "emergency_static"},
        {"actual_provider": "ollama-local", "actual_model": "model", "response_source": "persisted_history"},
    ],
)
async def test_recovery_rejects_unverified_generation_receipts(meta):
    request, decision, plan, meter = _authorized_turn()

    class Runtime:
        async def _run_simple(self, *_args, **_kwargs):
            return "Text that must not count as a model completion.", meta

    assert await _attempt(Runtime(), request, decision, plan, meter) is None
