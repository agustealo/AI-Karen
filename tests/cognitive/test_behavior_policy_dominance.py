from __future__ import annotations

import pytest

from ai_karen_engine.core.contracts.cognitive import PolicySnapshot
from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorSelectionContext,
    BehaviorType,
)
from ai_karen_engine.core.cortex.behavior.selector import BehaviorSelector


@pytest.mark.cognitive
def test_policy_blocked_behavior_cannot_win_on_score() -> None:
    context = BehaviorSelectionContext(
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="tenant-test",
        policy_constraints=PolicySnapshot(
            decision_id="policy-1",
            blocked_behaviors=(BehaviorType.USE_CAPABILITY.value,),
            risk=0.0,
        ),
    )
    candidates = [
        BehaviorCandidate(
            candidate_id="blocked-high-score",
            behavior_type=BehaviorType.USE_CAPABILITY,
            confidence=1.0,
        ),
        BehaviorCandidate(
            candidate_id="allowed-response",
            behavior_type=BehaviorType.RESPOND,
            confidence=0.9,
        ),
    ]

    decision = BehaviorSelector().select(context, candidates)
    assert decision.selected_behavior == BehaviorType.RESPOND
    assert all(
        candidate.behavior_type != BehaviorType.USE_CAPABILITY
        for candidate in decision.alternatives
    )


@pytest.mark.cognitive
def test_policy_constraint_flag_is_hard_denial() -> None:
    context = BehaviorSelectionContext(
        request_id="request-2",
        correlation_id="correlation-2",
        tenant_id="tenant-test",
    )
    candidates = [
        BehaviorCandidate(
            candidate_id="blocked",
            behavior_type=BehaviorType.USE_WORKFLOW,
            confidence=1.0,
            constraints=[BehaviorConstraint.POLICY_BLOCKED],
        ),
        BehaviorCandidate(
            candidate_id="allowed",
            behavior_type=BehaviorType.RESPOND,
            confidence=0.8,
        ),
    ]

    assert BehaviorSelector().select(context, candidates).selected_behavior == BehaviorType.RESPOND


@pytest.mark.cognitive
def test_tenant_restricted_candidate_is_deny_by_default() -> None:
    context = BehaviorSelectionContext(
        request_id="request-3",
        correlation_id="correlation-3",
        tenant_id="tenant-test",
    )
    candidates = [
        BehaviorCandidate(
            candidate_id="restricted",
            behavior_type=BehaviorType.DELEGATE,
            confidence=1.0,
            constraints=[BehaviorConstraint.TENANT_RESTRICTED],
        ),
        BehaviorCandidate(
            candidate_id="allowed",
            behavior_type=BehaviorType.RESPOND,
            confidence=0.8,
        ),
    ]

    assert BehaviorSelector().select(context, candidates).selected_behavior == BehaviorType.RESPOND


@pytest.mark.cognitive
def test_no_eligible_candidate_abstains() -> None:
    context = BehaviorSelectionContext(
        request_id="request-4",
        correlation_id="correlation-4",
        tenant_id="tenant-test",
        policy_constraints=PolicySnapshot(
            blocked_behaviors=(BehaviorType.USE_CAPABILITY.value,),
        ),
    )
    candidates = [
        BehaviorCandidate(
            candidate_id="blocked",
            behavior_type=BehaviorType.USE_CAPABILITY,
            confidence=1.0,
        )
    ]

    decision = BehaviorSelector().select(context, candidates)
    assert decision.selected_behavior == BehaviorType.ABSTAIN
    assert "no_eligible_candidates" in decision.reason_codes
