"""KCOG-01C1B2B2: deny fake dual-action execution evidence.

Real provider execution is exercised separately in the existing authenticated
Ollama production CI job. These tests assert the policy, scope, provider and
budget contracts without falsely claiming to run a model.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    ResponseProvenance,
    ResponseSource,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from scripts.ci.verification_strategy_pair_live_proof import (
    LiveStrategyProofError,
    require_authorized_execution,
    require_gateway_receipt,
    run_pair,
)


def _context(*, correlation_id: str = "correlation-authenticated") -> ChatExecutionContext:
    return ChatExecutionContext(
        user_id="tenant-scoped-user",
        tenant_id="tenant-scoped-tenant",
        session_id="scoped-session",
        request_id="request-authenticated",
        correlation_id=correlation_id,
    )


async def _policy(*, verification: bool = False):
    ctx = _context()
    modes = ["verification"] if verification else []
    return await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            correlation_id=ctx.correlation_id,
            requested_reasoning_modes=modes,
            max_model_calls=2,
            risk_signals={"score": 0.0, "categories": []},
            execution_topology={"reasoning_modes": modes, "max_steps": 6},
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verification", "selected", "topology", "modes"),
    [
        (False, "respond_direct", ExecutionTopology.DIRECT, []),
        (True, "verify_then_respond", ExecutionTopology.REASONING, ["verification"]),
    ],
)
async def test_actual_runtime_policy_grants_both_independently(
    verification, selected, topology, modes,
) -> None:
    decision = await _policy(verification=verification)
    plan = require_authorized_execution(
        decision, expected_action=selected, context=_context(),
    )
    assert decision.allowed
    assert plan.policy_decision_id == decision.decision_id
    assert plan.topology == topology
    assert plan.reasoning_modes == modes
    assert plan.budget.max_model_calls == 2
    assert plan.matches_execution_scope(
        user_id=_context().user_id,
        tenant_id=_context().tenant_id,
        session_id=_context().session_id,
        policy_decision_id=decision.decision_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"allowed": False},
    {"requires_human_gate": True},
    {"risk_level": "high"},
    {"denied_reasoning_modes": ["verification"]},
    {"allowed_reasoning_modes": ["verification", "causal"]},
    {"allowed_reasoning_modes": []},
    {"policy_version": ""},
    {"decision_id": ""},
])
async def test_denial_or_mode_drift_never_reaches_executor(change) -> None:
    policy = replace(await _policy(verification=True), **change)
    with pytest.raises(LiveStrategyProofError):
        require_authorized_execution(
            policy, expected_action="verify_then_respond", context=_context(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("authorized_user_id", "other-user"),
    ("authorized_tenant_id", "other-tenant"),
    ("authorized_session_id", "other-session"),
    ("correlation_id", "other-correlation"),
    ("max_model_calls", 1),
])
async def test_changed_scope_or_budget_denies_early(field, value) -> None:
    policy = await _policy(verification=True)
    policy.runtime_constraints[field] = value
    with pytest.raises(LiveStrategyProofError):
        require_authorized_execution(
            policy, expected_action="verify_then_respond", context=_context(),
        )


@pytest.mark.asyncio
async def test_denied_tools_do_not_grant_a_new_action() -> None:
    policy = await _policy(verification=True)
    policy.runtime_constraints["allowed_tools"] = ["web.search"]
    with pytest.raises(LiveStrategyProofError):
        require_authorized_execution(
            policy, expected_action="verify_then_respond", context=_context(),
        )


def _observed(*, verification: bool = False):
    context = _context()
    decision = ExecutionDecision(
        topology=(
            ExecutionTopology.REASONING if verification else ExecutionTopology.DIRECT
        ),
        reasoning_modes=["verification"] if verification else [],
        policy_decision_id="scoped-policy-decision",
        policy_version="v2",
        max_model_calls=2,
        max_steps=6,
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "A safe test statement."}],
        context=context,
        preferred_provider="ollama",
        preferred_model="installed-model",
    )
    metadata = {
        "actual_provider": "ollama",
        "actual_model": "installed-model",
        "response_source": "model",
        "degraded_mode": False,
        "fallback_level": 0,
        "provenance": ResponseProvenance(
            response_source=ResponseSource.MODEL,
            provider="ollama",
            model="installed-model",
            decision_id=decision.policy_decision_id,
            correlation_id=context.correlation_id,
        ),
    }
    if verification:
        metadata.update({
            "reasoning_generation_mode": "model_after_authorized_reasoning",
            "reasoning_activation": "core_defaults",
            "reasoning_status": "abstained",
            "reasoning_id": "actually-executed-reasoner",
            "reasoning_model_calls": 0,
            "reasoning_steps": 1,
            "reasoning_model_attribution_status": "not_executed",
            "verification_strategy_executed": True,
            "reasoning_modes": ["verification"],
        })
    meter = SimpleNamespace(
        model_calls=1,
        reasoning_steps=1 if verification else 0,
        exhausted=False,
    )
    return {
        "metadata": metadata,
        "text": "Model response.",
        "decision": decision,
        "request": request,
        "meter": meter,
        "expected_model": "installed-model",
        "verification": verification,
    }


@pytest.mark.parametrize("source", ["model", "provider_runtime", "openai_compatible_engine"])
@pytest.mark.parametrize("verification", [False, True])
def test_canonical_non_fallback_gateway_sources_are_genuine_model_receipts(
    source: str, verification: bool,
) -> None:
    payload = _observed(verification=verification)
    payload["metadata"]["response_source"] = source
    require_gateway_receipt(**payload)


@pytest.mark.parametrize("verification", [False, True])
def test_valid_typed_receipt_meets_structural_contract(verification) -> None:
    # A fixture receipt is intentionally not real model execution. The live
    # Ollama workflow is required before a merge may claim operational proof.
    require_gateway_receipt(**_observed(verification=verification))


@pytest.mark.parametrize("field,value", [
    ("actual_model", "invented-model"),
    ("actual_provider", "external"),
    ("response_source", "static"),
    ("response_source", "fallback_provider_runtime"),
    ("response_source", "model_unavailable"),
    ("fallback_level", 1),
    ("degraded_mode", True),
    ("provenance", None),
])
def test_mismatched_or_unobserved_gateway_receipt_is_denied(field, value) -> None:
    payload = _observed(verification=True)
    payload["metadata"][field] = value
    with pytest.raises(LiveStrategyProofError):
        require_gateway_receipt(**payload)


@pytest.mark.parametrize("change", [
    {"decision_id": "another-policy"},
    {"correlation_id": "another-correlation"},
    {"provider": "another-provider"},
    {"model": "another-model"},
    {"response_source": ResponseSource.CACHED},
])
def test_forged_provenance_is_denied(change) -> None:
    payload = _observed(verification=True)
    payload["metadata"]["provenance"] = replace(
        payload["metadata"]["provenance"], **change,
    )
    with pytest.raises(LiveStrategyProofError):
        require_gateway_receipt(**payload)


@pytest.mark.parametrize("changed", [
    {"reasoning_status": "failed"},
    {"reasoning_id": None},
    {"reasoning_generation_mode": "reasoning_only"},
    {"reasoning_activation": "runtime_composed"},
    {"reasoning_model_calls": 1},
    {"reasoning_steps": 0},
    {"reasoning_modes": ["unapproved"]},
    {"verification_strategy_executed": False},
    {"verification_strategy_executed": None},
])
def test_fake_reasoning_chain_is_denied(changed) -> None:
    payload = _observed(verification=True)
    payload["metadata"].update(changed)
    with pytest.raises(LiveStrategyProofError):
        require_gateway_receipt(**payload)


@pytest.mark.asyncio
async def test_live_runner_fails_closed_without_explicit_isolated_ci_enable(
    monkeypatch,
) -> None:
    monkeypatch.delenv("KAREN_CI_DUAL_STRATEGY_PROOF", raising=False)
    with pytest.raises(
        LiveStrategyProofError, match="isolated_ci_approval_or_identity_missing",
    ):
        await run_pair(
            user_id="user",
            tenant_id="tenant",
            model="not-actually-installed",
        )


@pytest.mark.parametrize("verification", [False, True])
@pytest.mark.parametrize(
    ("field", "value", "typed"),
    [
        ("fallback_level", 1, True),
        ("degradation_reason", "provider_changed", True),
        ("used_fallback", True, False),
        ("generation_error", True, False),
    ],
)
def test_b2c1_live_receipt_rejects_hidden_fallback_provenance(
    verification: bool, field: str, value: object, typed: bool,
) -> None:
    payload = _observed(verification=verification)
    if typed:
        provenance = payload["metadata"]["provenance"]
        payload["metadata"]["provenance"] = replace(
            provenance, **{field: value},
        )
    else:
        payload["metadata"][field] = value
    with pytest.raises(LiveStrategyProofError, match="gateway_degraded_or_fallback"):
        require_gateway_receipt(**payload)
