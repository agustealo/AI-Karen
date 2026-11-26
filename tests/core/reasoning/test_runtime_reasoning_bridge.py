from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.reasoning_bridge import (
    ReasoningActivationError,
    RuntimeReasoningBridge,
)


class DummySoftStrategy(ReasoningStrategyEngine):
    strategy_id = "soft_exploration"
    capabilities = ["soft_exploration"]
    supports_model_calls = True

    async def execute(self, request, context, evidence, budget):  # pragma: no cover
        raise AssertionError("activation tests do not execute the strategy")


@dataclass
class DummyComposed:
    strategy: ReasoningStrategyEngine
    prepared_prompt: str = "prepared\n<|soft_reasoning|>"
    prompt_version: str = "v1.0.0"
    provider_id: str = "builtin_transformers"
    model_id: str = "local-model"
    runtime_engine: str = "transformers:first_token_embedding_hook:v2"
    marker_token: str = "<|soft_reasoning|>"
    marker_token_id: int = 42
    profile: str = "paper_2025"
    maximum_total_model_calls: int = 31
    reserved_model_calls: object = field(default_factory=lambda: lambda: 0)


class DummyComposer:
    def compose_paper_2025(self, **kwargs):
        return DummyComposed(strategy=DummySoftStrategy())


def _decision(*, model_calls: int = 31) -> ExecutionDecision:
    return ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        max_steps=4,
        max_model_calls=model_calls,
        policy_decision_id="policy-1",
    )


def _plan(*, model_calls: int = 31) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id=f"exec-{uuid4().hex}",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id="tenant-1",
        authorized_session_id="session-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        budget=ExecutionBudget(
            max_reasoning_steps=4,
            max_model_calls=model_calls,
        ),
    )


def _bound_scope(plan):
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import PolicyDecision, RuntimePolicyEnforcer

    context = ChatExecutionContext(
        user_id="user-1", tenant_id="tenant-1", session_id="session-1",
        request_id="request-1", correlation_id="correlation-1",
        authenticated_user=UserData(
            user_id="user-1", tenant_id="tenant-1", roles=["user"], permissions=[],
            is_active=True, is_verified=True,
        ),
    )
    meter = ExecutionBudgetMeter(plan.budget)
    issuer = RuntimePolicyEnforcer()
    decision = PolicyDecision(
        decision_id=plan.policy_decision_id, policy_version="fixture", allowed=True,
        runtime_constraints={
            "authorized_user_id": context.user_id,
            "authorized_tenant_id": context.tenant_id,
            "authorized_session_id": context.session_id,
            "correlation_id": context.correlation_id,
            "max_model_calls": plan.budget.max_model_calls,
        },
    )
    issuer._record_issued_model_decision(decision)
    issuer.bind_chat_model_policy(context=context, decision=decision)
    context.bind_runtime_model_authority(plan, meter)
    meter.start()
    return context, meter


@pytest.mark.asyncio
async def test_soft_reasoning_activation_injects_runtime_composed_strategy(monkeypatch) -> None:
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module,
        "get_runtime_soft_reasoning_composer",
        lambda: DummyComposer(),
    )

    plan = _plan()
    context, meter = _bound_scope(plan)
    activation = await RuntimeReasoningBridge().activate(
        objective="Solve the problem",
        evidence=["evidence"],
        decision=_decision(),
        plan=plan,
        preferred_provider="builtin_transformers",
        preferred_model="local-model",
        authenticated_context=context, execution_meter=meter,
    )

    assert activation.reasoning_modes == ("soft_exploration",)
    assert activation.reserved_model_calls() == 0
    assert activation.request_metadata["soft_reasoning_profile"] == "paper_2025"
    assert activation.request_metadata["soft_reasoning_prompt_version"] == "v1.0.0"
    assert activation.runtime_metadata["reasoning_activation"] == "runtime_composed"
    assert activation.runtime_metadata["soft_reasoning_provider"] == "builtin_transformers"
    assert activation.runtime_metadata["soft_reasoning_model"] == "local-model"
    assert any(
        strategy.strategy_id == "soft_exploration"
        for strategy in activation.executor._strategies
    )


@pytest.mark.parametrize("model_calls", [10, 30])
@pytest.mark.asyncio
async def test_soft_reasoning_activation_fails_closed_when_budget_is_too_small(monkeypatch, model_calls) -> None:
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module,
        "get_runtime_soft_reasoning_composer",
        lambda: DummyComposer(),
    )

    plan = _plan(model_calls=model_calls)
    context, meter = _bound_scope(plan)
    monkeypatch.setattr(
        bridge_module, "get_runtime_soft_reasoning_composer",
        lambda: pytest.fail("budget must be checked before model preparation"),
    )
    with pytest.raises(
        ReasoningActivationError,
        match="requires a model-call budget of at least 31",
    ) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve the problem",
            evidence=[],
            decision=_decision(model_calls=model_calls),
            plan=plan,
            preferred_provider=None,
            preferred_model=None,
            authenticated_context=context, execution_meter=meter,
        )

    assert exc_info.value.code == "soft_reasoning_model_budget_insufficient"


@pytest.mark.asyncio
async def test_reasoning_activation_rejects_mode_not_authorized_by_plan() -> None:
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["soft_exploration"],
        max_model_calls=30,
        policy_decision_id="policy-1",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["causal"],
        budget=ExecutionBudget(max_model_calls=30),
    )

    with pytest.raises(ReasoningActivationError) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve",
            evidence=[],
            decision=decision,
            plan=plan,
            preferred_provider=None,
            preferred_model=None,
        )

    assert exc_info.value.code == "reasoning_mode_not_authorized"


@pytest.mark.asyncio
async def test_reasoning_activation_rejects_empty_cortex_mode_set() -> None:
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=[],
        policy_decision_id="policy-1",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["evidence_synthesis"],
        budget=ExecutionBudget(max_model_calls=10),
    )

    with pytest.raises(ReasoningActivationError) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve",
            evidence=[],
            decision=decision,
            plan=plan,
            preferred_provider=None,
            preferred_model=None,
        )

    assert exc_info.value.code == "reasoning_mode_not_requested"


@pytest.mark.asyncio
async def test_reasoning_activation_rejects_empty_policy_mode_set() -> None:
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["causal"],
        policy_decision_id="policy-1",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        reasoning_modes=[],
        budget=ExecutionBudget(max_model_calls=10),
    )

    with pytest.raises(ReasoningActivationError) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve",
            evidence=[],
            decision=decision,
            plan=plan,
            preferred_provider=None,
            preferred_model=None,
        )

    assert exc_info.value.code == "reasoning_mode_not_authorized"


def test_execution_decision_keeps_reasoning_and_model_call_budgets_distinct() -> None:
    decision = _decision(model_calls=30)

    assert decision.max_steps == 4
    assert decision.max_model_calls == 30


def test_execution_decision_canonicalizes_reasoning_mode_aliases_once() -> None:
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verify", "refine", "synthesis"],
    )

    assert decision.reasoning_modes == [
        "verification",
        "refinement",
        "evidence_synthesis",
    ]


@pytest.mark.parametrize("replacement", ["missing", "fresh_meter", "cloned_plan"])
@pytest.mark.asyncio
async def test_soft_activation_rejects_unbound_authority_before_composition(monkeypatch, replacement):
    from dataclasses import replace
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    plan = _plan()
    context, meter = _bound_scope(plan)
    monkeypatch.setattr(
        bridge_module, "get_runtime_soft_reasoning_composer",
        lambda: pytest.fail("unbound authority reached model preparation"),
    )
    if replacement == "missing":
        context = None
    elif replacement == "fresh_meter":
        meter = ExecutionBudgetMeter(plan.budget)
    else:
        plan = replace(plan)
    with pytest.raises(ReasoningActivationError) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve", evidence=[], decision=_decision(), plan=plan,
            preferred_provider=None, preferred_model=None,
            authenticated_context=context, execution_meter=meter,
        )
    assert exc_info.value.code == "soft_reasoning_original_admission_required"


@pytest.mark.asyncio
async def test_soft_activation_cannot_reuse_spent_model_budget(monkeypatch):
    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    plan = _plan()
    context, meter = _bound_scope(plan)
    assert await meter.consume_model_call()
    monkeypatch.setattr(
        bridge_module, "get_runtime_soft_reasoning_composer",
        lambda: pytest.fail("spent budget reached model preparation"),
    )
    with pytest.raises(ReasoningActivationError) as exc_info:
        await RuntimeReasoningBridge().activate(
            objective="Solve", evidence=[], decision=_decision(), plan=plan,
            preferred_provider=None, preferred_model=None,
            authenticated_context=context, execution_meter=meter,
        )
    assert exc_info.value.code == "soft_reasoning_model_budget_insufficient"
    assert meter.model_calls == 1


@pytest.mark.parametrize("replacement", ["model", "tokenizer", "path"])
def test_native_borrow_rejects_replacement_without_loading(monkeypatch, replacement):
    from threading import RLock
    from types import SimpleNamespace

    from ai_karen_engine.core.model_runtime.provider_contracts import ProviderNotAvailable
    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import TransformersRuntime

    runtime = object.__new__(TransformersRuntime)
    runtime._generation_lock = RLock()
    runtime.model_path = "/local/model-a"
    runtime._pipeline = SimpleNamespace(model=object(), tokenizer=object())
    monkeypatch.setattr(runtime, "warm", lambda *args, **kwargs: pytest.fail("unexpected load"))
    with runtime.borrow_generation_components("/local/model-a") as original:
        assert original[0] is runtime._pipeline.model
        assert original[1] is runtime._pipeline.tokenizer
    if replacement == "path":
        runtime.model_path = "/local/model-b"
    else:
        setattr(runtime._pipeline, replacement, object())
    with pytest.raises(ProviderNotAvailable, match="identity_drift"):
        with runtime.borrow_generation_components("/local/model-a", expected=original):
            pytest.fail("replaced identity admitted")


@pytest.mark.asyncio
async def test_live_preparation_is_owned_across_repeated_cancellation(monkeypatch):
    import asyncio
    import threading

    import ai_karen_engine.core.runtime.reasoning_bridge as bridge_module

    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    retired = threading.Event()
    plan = _plan()
    context, meter = _bound_scope(plan)

    class BlockingComposer:
        def compose_paper_2025(self, **kwargs):
            assert threading.get_ident() != loop_thread
            checkpoint = kwargs["preparation_checkpoint"]
            try:
                checkpoint()
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("test preparation release deadline")
                checkpoint()
                pytest.fail("cancelled preparation published")
            finally:
                retired.set()

    loop_thread = threading.get_ident()
    monkeypatch.setattr(bridge_module, "get_runtime_soft_reasoning_composer", BlockingComposer)
    task = asyncio.create_task(RuntimeReasoningBridge().activate(
        objective="Solve", evidence=[], decision=_decision(), plan=plan,
        preferred_provider=None, preferred_model=None,
        authenticated_context=context, execution_meter=meter,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not retired.is_set()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=3)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert retired.is_set()
    assert meter.model_calls == 0
