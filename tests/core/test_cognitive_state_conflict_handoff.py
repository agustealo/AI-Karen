"""KCOG-01A1: scoped evidence conflict changes policy-gated cognition."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.context.contracts import (
    ContextEvidence,
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyDecision,
    PolicyReasonCode,
    RuntimePolicyEnforcer,
)


class FixedCortex:
    def __init__(self, decision: ExecutionDecision) -> None:
        self._decision = decision

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return self._decision


class EvidenceResolver:
    """Injects only after the policy-stage context resolution check."""

    def __init__(
        self,
        *,
        user_id: str = "user-a",
        tenant_id: str = "tenant-a",
        conflict: bool = True,
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.conflict = conflict

    async def resolve(self, request, cognitive_context):
        items = [
            ContextEvidence(
                evidence_id=ident,
                source=EvidenceSource.MEMORY,
                content=content,
                provenance=EvidenceProvenance(resolver_id="memory_runtime"),
                scope=EvidenceScope(tenant_id=self.tenant_id, user_id=self.user_id),
                contradiction=(
                    EvidenceContradiction(
                        status=EvidenceContradictionStatus.CONFIRMED,
                        conflicting_evidence_ids=("e2",),
                    )
                    if ident == "e1" and self.conflict
                    else EvidenceContradiction(
                        status=EvidenceContradictionStatus.NONE,
                    )
                ),
            )
            for ident, content in (("e1", "A"), ("e2", "B"))
        ]
        cognitive_context.evidence = items
        cognitive_context.unresolved_sources = [
            source
            for source in cognitive_context.unresolved_sources
            if source != EvidenceSource.MEMORY.value
        ]
        return cognitive_context


class DenyMemoryPolicy(RuntimePolicyEnforcer):
    async def evaluate(self, request):
        if request.action == "context.resolve":
            return PolicyDecision(
                decision_id="policy-deny-memory",
                policy_version="v2",
                allowed=True,
                reason_codes=[PolicyReasonCode.POLICY_CHECK_PASSED],
                allowed_capabilities=[],
                denied_capabilities=["memory.read"],
            )
        return await super().evaluate(request)


class DenyVerificationPolicy(RuntimePolicyEnforcer):
    async def _evaluate_policy_request(self, request):
        # Return the final policy decision to the canonical evaluate issuer,
        # instead of replacing an already-issued decision afterward.
        policy = await super()._evaluate_policy_request(request)
        if request.action != "context.resolve":
            return replace(
                policy,
                allowed_reasoning_modes=[],
                denied_reasoning_modes=["verification"],
                reasoning_denial_reasons={
                    "verification": ["not_authorized_for_test"],
                },
            )
        return policy


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Analyze conflicting evidence"}],
        context=ChatExecutionContext(
            user_id="user-a",
            tenant_id="tenant-a",
            session_id="session-a",
            request_id="request-a",
            correlation_id="correlation-a",
            authenticated_user=UserData(
                user_id="user-a",
                tenant_id="tenant-a",
                roles=["user"],
                permissions=[],
                is_active=True,
                is_verified=True,
            ),
        ),
    )


def _pipeline(
    resolver: EvidenceResolver,
    policy: RuntimePolicyEnforcer | None = None,
    max_steps: int = 5,
) -> RuntimeDecisionPipeline:
    return RuntimeDecisionPipeline(
        cortex=FixedCortex(
            ExecutionDecision(
                intent="general_assist",
                memory_recall_required=True,
                memory_scope="user",
                max_steps=max_steps,
            ),
        ),
        policy=policy or RuntimePolicyEnforcer(),
        evidence_resolver=resolver,
    )


def test_confirmed_scoped_conflict_requests_authorized_verification() -> None:
    result = asyncio.run(_pipeline(EvidenceResolver()).decide(_request()))

    assert result.topology == ExecutionTopology.REASONING
    assert result.reasoning_modes == ["verification"]
    assert result.cognitive_state is not None
    assert result.cognitive_state.tenant_id == "tenant-a"
    assert result.cognitive_state.user_id == "user-a"
    assert result.cognitive_state.context.selected_count == 2
    assert result.cognitive_state.meta.status == "conflicted"
    assert result.cognitive_state.meta.metadata["calibration_status"] == "not_evaluated"
    assert result.cognitive_state.meta.metadata["verification_authorized"] is True
    assert result.cognitive_state.policy.policy_id == result.policy_decision_id
    assert "cognitive_conflict_verification_requested" in result.reason_codes


def test_absent_conflict_does_not_invent_reasoning() -> None:
    result = asyncio.run(
        _pipeline(EvidenceResolver(conflict=False)).decide(_request())
    )

    assert result.topology == ExecutionTopology.DIRECT
    assert result.reasoning_modes == []
    assert result.cognitive_state.meta.status == "unassessed"
    assert result.cognitive_state.meta.metadata["confidence_status"] == "unverified"


def test_cross_tenant_evidence_never_triggers_extra_reasoning() -> None:
    result = asyncio.run(
        _pipeline(EvidenceResolver(tenant_id="other-tenant")).decide(_request())
    )

    assert result.reasoning_modes == []
    assert result.cognitive_state.meta.status == "unassessed"
    assert result.policy_constraints["cognitive_conflict_evidence_ids"] == []


def test_cross_user_evidence_never_triggers_extra_reasoning() -> None:
    result = asyncio.run(
        _pipeline(EvidenceResolver(user_id="another-user")).decide(_request())
    )

    assert result.reasoning_modes == []
    assert result.cognitive_state.meta.status == "unassessed"


def test_denied_memory_evidence_cannot_induce_verification() -> None:
    result = asyncio.run(
        _pipeline(
            EvidenceResolver(),
            policy=DenyMemoryPolicy(),
        ).decide(_request())
    )

    assert result.reasoning_modes == []
    assert result.cognitive_state.meta.status == "unassessed"
    assert result.cognitive_state.context.selected_count == 0
    assert "memory.read" in result.forbidden_capabilities


def test_runtime_policy_can_deny_requested_verification() -> None:
    result = asyncio.run(
        _pipeline(EvidenceResolver(), policy=DenyVerificationPolicy()).decide(
            _request()
        )
    )

    assert "cognitive_conflict_verification_requested" in result.reason_codes
    assert "verification" not in result.reasoning_modes
    assert result.topology == ExecutionTopology.DIRECT
    assert result.cognitive_state.meta.status == "conflicted"
    assert result.cognitive_state.meta.metadata["verification_authorized"] is False


def test_no_steps_does_not_expand_cognitive_budget() -> None:
    result = asyncio.run(
        _pipeline(EvidenceResolver(), max_steps=0).decide(_request())
    )
    assert result.reasoning_modes == []
    assert "cognitive_conflict_verification_budget_exhausted" in result.reason_codes
