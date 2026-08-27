from __future__ import annotations

import asyncio

from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimeLevel,
    RuntimePolicyEnforcer,
    SOFT_EXPLORATION_MIN_MODEL_CALLS,
    authorize_reasoning_modes,
)


def test_empty_request_stays_empty() -> None:
    result = authorize_reasoning_modes([])
    assert result.requested_modes == ()
    assert result.allowed_modes == ()
    assert result.denied_modes == ()


def test_aliases_are_canonicalized() -> None:
    result = authorize_reasoning_modes(["verify", "refine", "synthesis"])
    assert result.allowed_modes == (
        "verification",
        "refinement",
        "evidence_synthesis",
    )


def test_soft_exploration_requires_compute_budget() -> None:
    denied = authorize_reasoning_modes(
        ["soft_exploration"],
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS - 1,
    )
    allowed = authorize_reasoning_modes(
        ["soft_exploration"],
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert denied.denied_modes == ("soft_exploration",)
    assert denied.denial_reasons["soft_exploration"] == (
        "model_call_budget_insufficient",
    )
    assert allowed.allowed_modes == ("soft_exploration",)


def test_reduced_runtime_denies_soft_exploration() -> None:
    result = authorize_reasoning_modes(
        ["verification", "soft_exploration"],
        runtime_level="REDUCED",
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert result.allowed_modes == ("verification",)
    assert result.denied_modes == ("soft_exploration",)


def test_high_risk_preserves_verification_and_denies_exploration() -> None:
    result = authorize_reasoning_modes(
        ["verification", "counterfactual", "soft_exploration"],
        runtime_level="FULL",
        risk_level="high",
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert result.allowed_modes == ("verification",)
    assert result.denied_modes == ("counterfactual", "soft_exploration")


def test_emergency_runtime_allows_only_verification_and_evidence_synthesis() -> None:
    result = authorize_reasoning_modes(
        ["causal", "verification", "evidence_synthesis", "refinement"],
        runtime_level="EMERGENCY",
    )
    assert result.allowed_modes == ("verification", "evidence_synthesis")
    assert result.denied_modes == ("causal", "refinement")


def test_runtime_policy_returns_typed_allowed_and_denied_reasoning_modes() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=["verification", "soft_exploration"],
                max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS - 1,
                runtime_level=RuntimeLevel.FULL,
            )
        )
        assert result.allowed is True
        assert result.allowed_reasoning_modes == ["verification"]
        assert result.denied_reasoning_modes == ["soft_exploration"]
        assert result.reasoning_denial_reasons["soft_exploration"] == [
            "model_call_budget_insufficient"
        ]

    asyncio.run(run())


def test_authorized_plan_uses_policy_reasoning_modes_not_requested_modes() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=["verification", "soft_exploration"],
                max_model_calls=10,
                runtime_level=RuntimeLevel.FULL,
            )
        )
        plan = result.to_authorized_plan()
        assert plan.reasoning_modes == ["verification"]
        assert "soft_exploration" not in plan.reasoning_modes

    asyncio.run(run())


def test_policy_never_invents_reasoning_mode() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=[],
                max_model_calls=100,
            )
        )
        assert result.allowed_reasoning_modes == []
        assert result.denied_reasoning_modes == []
        assert result.to_authorized_plan().reasoning_modes == []

    asyncio.run(run())
