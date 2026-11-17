"""KCOG-01C1B2B1: observed selected execution is not dual-action evidence.

No invented providers, model calls, strategy propensities, reviewer labels, or
policy promotion. Source tests use typed gateway receipts; hardware and
independent answer-correctness acceptance remain separate release gates.
"""

from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.contracts import (
    ExecutionTopology,
    ResponseProvenance,
    ResponseSource,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RiskLevel,
)
from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    reset_correlation_context,
    set_correlation_context,
)


CORRELATION_ID = "kcog-b2b1-corr"
POLICY_ID = "kcog-b2b1-policy"


def _decision(*, verification: bool = False) -> ExecutionDecision:
    return ExecutionDecision(
        topology=(
            ExecutionTopology.REASONING if verification
            else ExecutionTopology.DIRECT
        ),
        reasoning_modes=["verification"] if verification else [],
        policy_decision_id=POLICY_ID,
        policy_version="b2b-v1",
        risk_level=RiskLevel.LOW,
        max_model_calls=4,
    )


def _receipt(*, verification: bool = False) -> dict:
    result = {
        "response_source": "model",
        "actual_provider": "ollama",
        "actual_model": "measured-local-model",
        "fallback_level": 0,
        "degraded_mode": False,
        "provenance": ResponseProvenance(
            response_source=ResponseSource.MODEL,
            provider="ollama",
            model="measured-local-model",
            engine="ollama",
            correlation_id=CORRELATION_ID,
            decision_id=POLICY_ID,
        ),
    }
    if verification:
        result.update({
            "reasoning_id": "reason-real-executor",
            "reasoning_status": "abstained",
            "reasoning_activation": "core_defaults",
            "reasoning_generation_mode": "model_after_authorized_reasoning",
            "reasoning_model_calls": 0,
            "reasoning_model_attribution_status": "not_executed",
            "verification_strategy_executed": True,
            "reasoning_steps": 2,
            "reasoning_modes": ["verification"],
        })
    return result


def _inspect(
    *,
    verification: bool = False,
    receipt: dict | None = None,
    decision: ExecutionDecision | None = None,
    correlation: str | None = CORRELATION_ID,
    complete: bool = True,
    success: bool = True,
    transcript_status: str = "persisted",
    calls: int = 1,
):
    return ChatRuntime._inspect_selected_strategy_execution(
        decision or _decision(verification=verification),
        _receipt(verification=verification) if receipt is None else receipt,
        response_completed=complete,
        success=success,
        transcript_status=transcript_status,
        observed_model_calls=calls,
        correlation_id=correlation,
    )


@pytest.mark.parametrize("verification", [False, True])
def test_selected_path_accepts_genuine_provider_runtime_source(
    verification: bool,
) -> None:
    receipt = _receipt(verification=verification)
    receipt["response_source"] = "provider_runtime"
    observed = _inspect(verification=verification, receipt=receipt)
    assert observed is not None
    assert observed["status"] == "selected_runtime_path_observed"
    assert observed["provider_receipt_observed"] is True
    assert observed["ope_eligible"] is False


@pytest.mark.parametrize("verification", [False, True])
def test_only_chosen_runtime_path_can_be_observed(verification: bool) -> None:
    observed = _inspect(verification=verification)
    assert observed is not None
    assert observed["status"] == "selected_runtime_path_observed"
    assert observed["selected_action"] == (
        "verify_then_respond" if verification else "respond_direct"
    )
    assert observed["provider_receipt_observed"] is True
    assert observed["transcript_durable"] is True
    assert observed["policy_decision_id"] == POLICY_ID
    assert observed["actual_provider"] == "ollama"
    assert observed["actual_model"] == "measured-local-model"
    if verification:
        assert observed["reasoning_status"] == "abstained"
        assert observed["reasoning_id"] == "reason-real-executor"
    else:
        assert observed["reasoning_status"] == "not_applicable"
    assert observed["execution_observation_only"] is True
    assert observed["independent_verification_proven"] is False
    assert observed["dual_action_eligibility_established"] is False
    assert observed["randomized_selection"] is False
    assert observed["ope_eligible"] is False
    assert "action_probabilities" not in observed
    assert "candidate_probabilities" not in observed


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_provider", "forged-provider"),
        ("actual_model", "forged-model"),
        ("response_source", "reasoning"),
        ("response_source", "fallback_provider_runtime"),
        ("response_source", "model_unavailable"),
        ("fallback_level", 1),
        ("degraded_mode", True),
    ],
)
def test_provider_metadata_cannot_substitute_for_gateway_receipt(
    field: str, value: object,
) -> None:
    metadata = _receipt(verification=True)
    metadata[field] = value
    evidence = _inspect(verification=True, receipt=metadata)
    assert evidence is not None
    assert evidence["status"] == "unverified"
    assert evidence["provider_receipt_observed"] is False
    assert evidence["actual_provider"] is None
    assert evidence["actual_model"] is None
    assert "model_generation_receipt_unverified" in evidence["reason_codes"]


@pytest.mark.parametrize(
    "forgery",
    [
        {"provider": "other-provider"},
        {"model": "other-model"},
        {"decision_id": "other-policy"},
        {"correlation_id": "other-correlation"},
        {"response_source": ResponseSource.CACHED},
    ],
)
def test_forged_typed_provenance_never_proves_execution(forgery: dict) -> None:
    metadata = _receipt(verification=True)
    original = metadata["provenance"]
    metadata["provenance"] = replace(original, **forgery)
    observed = _inspect(verification=True, receipt=metadata)
    assert observed is not None
    assert observed["status"] == "unverified"
    assert observed["provider_receipt_observed"] is False


@pytest.mark.parametrize("changed", [
    {"reasoning_id": None},
    {"reasoning_status": "failed"},
    {"reasoning_activation": "runtime_composed"},
    {"reasoning_generation_mode": "unverified"},
    {"reasoning_model_calls": 1},
    {"reasoning_model_attribution_status": "unverified"},
    {"reasoning_steps": 0},
    {"reasoning_modes": ["unapproved"]},
    {"verification_strategy_executed": False},
    {"verification_strategy_executed": None},
])
def test_reasoning_receipt_must_match_actual_authorized_chain(changed: dict) -> None:
    metadata = _receipt(verification=True)
    metadata.update(changed)
    evidence = _inspect(verification=True, receipt=metadata)
    assert evidence is not None
    assert evidence["status"] == "unverified"
    assert "reasoning_execution_receipt_unverified" in evidence["reason_codes"]


@pytest.mark.parametrize("kwargs", [
    {"correlation": None},
    {"correlation": "wrong-correlation"},
    {"complete": False},
    {"success": False},
    {"transcript_status": "failed"},
    {"transcript_status": "skipped"},
    {"calls": 0},
])
def test_no_outcome_without_complete_scoped_durable_execution(
    kwargs: dict,
) -> None:
    evidence = _inspect(verification=True, **kwargs)
    assert evidence is not None
    assert evidence["status"] == "unverified"
    assert evidence["ope_eligible"] is False


@pytest.mark.parametrize("change", [
    {"risk_level": RiskLevel.HIGH},
    {"requires_human_gate": True},
    {"tool_requirements": ["web"]},
    {"plugin_candidates": ["telegram"]},
    {"requires_agent_delegation": True},
    {"reasoning_modes": ["causal", "verification"]},
    {"policy_decision_id": None},
    {"topology": ExecutionTopology.WORKFLOW},
])
def test_noncomparable_or_unauthorized_plans_get_no_strategy_receipt(
    change: dict,
) -> None:
    decision = replace(_decision(verification=True), **change)
    assert _inspect(verification=True, decision=decision) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("verification", [False, True])
async def test_canonical_outcome_recorder_gets_scoped_non_ope_receipt(
    verification: bool,
) -> None:
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._outcome_recorder = SimpleNamespace(
        record_execution_outcome_async=AsyncMock(),
    )
    token = set_correlation_context(CorrelationContext(
        correlation_id=CORRELATION_ID,
        tenant_id="tenant-scope",
        user_id="user-scope",
        request_id="request-scope",
    ))
    try:
        await runtime._record_execution_outcome(
            trajectory_id="trajectory-scope",
            decision=_decision(verification=verification),
            decision_observation_id="chosen-decision",
            text="Canonical gateway response.",
            start=time.time() - 0.01,
            meter=SimpleNamespace(
                model_calls=1, tool_calls=0, reasoning_steps=2,
            ),
            memory_meta={},
            success=True,
            transcript_meta={"transcript_persistence_status": "persisted"},
            provider_meta=_receipt(verification=verification),
        )
    finally:
        reset_correlation_context(token)
    kwargs = runtime._outcome_recorder.record_execution_outcome_async.await_args.kwargs
    assert kwargs["trajectory_id"] == "trajectory-scope"
    assert kwargs["decision_observation_id"] == "chosen-decision"
    observation = kwargs["metadata"]["selected_strategy_execution"]
    assert observation["status"] == "selected_runtime_path_observed"
    assert observation["ope_eligible"] is False
    assert observation["independent_verification_proven"] is False
    assert observation["randomized_selection"] is False


@pytest.mark.asyncio
async def test_durable_outcome_does_not_claim_missing_provider_receipt() -> None:
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._outcome_recorder = SimpleNamespace(
        record_execution_outcome_async=AsyncMock(),
    )
    token = set_correlation_context(CorrelationContext(
        correlation_id=CORRELATION_ID, tenant_id="tenant-scope",
        user_id="user-scope", request_id="request-scope",
    ))
    try:
        await runtime._record_execution_outcome(
            trajectory_id="trajectory-scope",
            decision=_decision(verification=True),
            decision_observation_id="chosen-decision",
            text="Reasoning-only text.",
            start=time.time() - 0.01,
            meter=SimpleNamespace(
                model_calls=0, tool_calls=0, reasoning_steps=2,
            ),
            memory_meta={},
            success=True,
            transcript_meta={"transcript_persistence_status": "persisted"},
            provider_meta={
                "response_source": "reasoning",
                "actual_provider": "pretend-model",
                "actual_model": "pretend-model",
                "reasoning_id": "reason-only",
                "reasoning_status": "success",
            },
        )
    finally:
        reset_correlation_context(token)
    kwargs = runtime._outcome_recorder.record_execution_outcome_async.await_args.kwargs
    evidence = kwargs["metadata"]["selected_strategy_execution"]
    assert evidence["status"] == "unverified"
    assert evidence["provider_receipt_observed"] is False
    assert evidence["actual_provider"] is None
    assert evidence["ope_eligible"] is False


@pytest.mark.parametrize("verification", [False, True])
@pytest.mark.parametrize(
    ("field", "value", "typed"),
    [
        ("fallback_level", 1, True),
        ("degradation_reason", "provider_changed", True),
        ("requested_provider", "unauthorized-provider", False),
        ("requested_model", "unselected-model", False),
        ("used_fallback", True, False),
        ("generation_error", True, False),
    ],
)
def test_b2c1_contradictory_provider_or_fallback_evidence_is_unverified(
    verification: bool, field: str, value: object, typed: bool,
) -> None:
    """Neither a typed receipt nor metadata may hide actual execution drift."""
    receipt = _receipt(verification=verification)
    if typed:
        receipt["provenance"] = replace(receipt["provenance"], **{field: value})
    else:
        receipt[field] = value
    observed = _inspect(verification=verification, receipt=receipt)
    assert observed is not None
    assert observed["status"] == "unverified"
    assert observed["provider_receipt_observed"] is False
    assert observed["actual_provider"] is None
    assert observed["actual_model"] is None
    assert "model_generation_receipt_unverified" in observed["reason_codes"]
    assert observed["independent_verification_proven"] is False
    assert observed["ope_eligible"] is False


@pytest.mark.parametrize("verification", [False, True])
def test_b2c1_cancelled_or_incomplete_execution_never_becomes_observed(
    verification: bool,
) -> None:
    observed = _inspect(
        verification=verification, success=False, complete=False,
        transcript_status="skipped",
    )
    assert observed is not None
    assert observed["status"] == "unverified"
    assert "response_execution_incomplete" in observed["reason_codes"]
    assert "transcript_persistence_unverified" in observed["reason_codes"]
    assert observed["dual_action_eligibility_established"] is False
    assert observed["ope_eligible"] is False
