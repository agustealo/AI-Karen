"""Canonical reasoning contract and executor tests."""

from __future__ import annotations

import asyncio
from dataclasses import fields

import pytest

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningDisposition,
    ReasoningErrorCode,
    ReasoningAssessment,
    ReasoningContradiction,
    ReasoningHypothesis,
    ReasoningEvidenceNeed,
    ReasoningEscalationRequest,
    ReasoningAction,
    EvidenceSensitivity,
    HypothesisStatus,
    ContradictionSeverity,
    ReasoningMode,
)
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor, EvidenceProvider, BudgetExhaustedError
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionContext,
    ExecutionTopology,
)


class PassthroughEvidenceProvider(EvidenceProvider):
    async def retrieve(self, request, context):
        return list(request.evidence)


class SimpleStrategy(ReasoningStrategyEngine):
    strategy_id = "simple"
    version = "v1"
    capabilities = ["synthesis"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 1

    async def execute(self, request, context, evidence, budget):
        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.COMPLETE.value,
            conclusion="simple strategy result",
            hypotheses=[
                ReasoningHypothesis(
                    hypothesis_id="h1",
                    statement="test hypothesis",
                    confidence=0.8,
                )
            ],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(confidence=0.8),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.COMPLETED.value,
        )


class EscalatingStrategy(ReasoningStrategyEngine):
    strategy_id = "escalating"
    version = "v1"
    capabilities = ["causal"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 1

    async def execute(self, request, context, evidence, budget):
        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.ESCALATE.value,
            conclusion="needs workflow",
            hypotheses=[],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.COMPLETED.value,
            escalation=ReasoningEscalationRequest(
                requested_topology="workflow",
                reason="multi_step_external_evidence",
            ),
        )


class EvidenceNeedingStrategy(ReasoningStrategyEngine):
    strategy_id = "evidence_needing"
    version = "v1"
    capabilities = ["verification"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 1

    async def execute(self, request, context, evidence, budget):
        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.REQUEST_EVIDENCE.value,
            conclusion="needs more evidence",
            hypotheses=[],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(),
            evidence_needs=[
                ReasoningEvidenceNeed(
                    capability="repository.read",
                    description="Need source file",
                    query="settings.py",
                    required=True,
                )
            ],
            suggested_next_actions=[],
            status=ReasoningStatus.WAITING_FOR_EVIDENCE.value,
        )


def test_reasoning_request_has_expected_fields():
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id="conv-1",
        objective="Why did CI pass but deploy fail?",
        reasoning_modes=["causal", "verification"],
        evidence=[],
        constraints={"reasoning_depth": "standard"},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    assert request.tenant_id == "tenant-a"
    assert request.reasoning_modes == ["causal", "verification"]
    assert request.schema_version == "v1"


def test_reasoning_result_has_expected_fields():
    result = ReasoningResult(
        reasoning_id="reasoning-1",
        disposition=ReasoningDisposition.COMPLETE.value,
        conclusion="causal chain identified",
        hypotheses=[],
        evidence=[],
        assumptions=["assumption-1"],
        unknowns=["unknown-1"],
        contradictions=[],
        assessment=ReasoningAssessment(confidence=0.8),
        evidence_needs=[],
        suggested_next_actions=[],
        status=ReasoningStatus.COMPLETED.value,
    )
    assert result.disposition == "complete"
    assert result.assumptions == ["assumption-1"]
    assert result.unknowns == ["unknown-1"]
    assert result.assessment.confidence == 0.8
    assert result.schema_version == "v1"


def test_reasoning_evidence_sensitivity():
    evidence = ReasoningEvidence(
        evidence_id="ev-1",
        type="config",
        source="config_file",
        source_ref="settings.py",
        content="provider=vLLM",
        tenant_id="tenant-a",
        sensitivity=EvidenceSensitivity.INTERNAL.value,
    )
    assert evidence.sensitivity == "internal"
    assert evidence.valid_at is None


def test_reasoning_hypothesis_status():
    hypothesis = ReasoningHypothesis(
        hypothesis_id="hyp-1",
        statement="pool exhaustion",
        status=HypothesisStatus.SUPPORTED.value,
    )
    assert hypothesis.status == "supported"


def test_reasoning_contradiction_severity():
    contradiction = ReasoningContradiction(
        claim_a="provider=vLLM",
        claim_b="provider=Ollama",
        severity=ContradictionSeverity.CRITICAL.value,
        resolvable=False,
    )
    assert contradiction.severity == "critical"
    assert contradiction.resolvable is False


def test_executor_validates_tenant_scope():
    executor = ReasoningExecutor()
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=["synthesis"],
        evidence=[
            ReasoningEvidence(
                evidence_id="ev-1",
                type="memory",
                source="memory",
                source_ref="",
                content="cross-tenant",
                tenant_id="tenant-b",
            )
        ],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        budget=ExecutionBudget(),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.status == ReasoningStatus.FAILED.value
    assert result.error_code == ReasoningErrorCode.EVIDENCE_SCOPE_VIOLATION.value


def test_executor_runs_simple_strategy():
    executor = ReasoningExecutor(strategies=[SimpleStrategy()])
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=["synthesis"],
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        budget=ExecutionBudget(max_duration_ms=1000),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.status == ReasoningStatus.COMPLETED.value
    assert result.disposition == ReasoningDisposition.COMPLETE.value
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].statement == "test hypothesis"


def test_executor_handles_escalation():
    executor = ReasoningExecutor(strategies=[EscalatingStrategy()])
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=["causal"],
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        budget=ExecutionBudget(max_duration_ms=1000),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.disposition == ReasoningDisposition.ESCALATE.value
    assert result.escalation is not None
    assert result.escalation.requested_topology == "workflow"


def test_executor_handles_evidence_need():
    executor = ReasoningExecutor(strategies=[EvidenceNeedingStrategy()])
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=["verification"],
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        budget=ExecutionBudget(max_duration_ms=1000),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.disposition == ReasoningDisposition.REQUEST_EVIDENCE.value
    assert len(result.evidence_needs) == 1
    assert result.evidence_needs[0].capability == "repository.read"


def test_executor_no_strategies():
    executor = ReasoningExecutor(strategies=[])
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=[],
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.REASONING,
        budget=ExecutionBudget(),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.status == ReasoningStatus.FAILED.value
    assert result.error_code == ReasoningErrorCode.STRATEGY_UNAVAILABLE.value


def test_executor_invalid_topology():
    executor = ReasoningExecutor(strategies=[SimpleStrategy()])
    request = ReasoningRequest(
        request_id="req-1",
        correlation_id="cx-1",
        tenant_id="tenant-a",
        user_id="user-1",
        conversation_id=None,
        objective="test",
        reasoning_modes=["synthesis"],
        evidence=[],
        constraints={},
        policy_decision_id="policy-1",
        budget=ReasoningBudget(),
        metadata={},
    )
    plan = AuthorizedExecutionPlan(
        execution_id="plan-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.DIRECT,
        budget=ExecutionBudget(),
    )
    context = ExecutionContext(
        request_id="req-1",
        correlation_id="cx-1",
        user_id="user-1",
        tenant_id="tenant-a",
    )

    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(request, plan, context)
    )
    assert result.status == ReasoningStatus.FAILED.value
    assert result.error_code == ReasoningErrorCode.INVALID_REQUEST.value
