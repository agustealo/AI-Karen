"""KCM decision evidence is task-scoped, independently reviewed, not mastery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyObservation,
)
from ai_karen_engine.core.intelligence.ml.verification_review_evidence import (
    GovernedVerificationReviewEvidence,
)
from ai_karen_engine.core.personalization.reviewed_decision_evidence import (
    KcmDecisionEvidenceHealth,
    KcmReviewedDecisionProjector,
)
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OTHER_USER = "dddddddd-dddd-dddd-dddd-dddddddddddd"
REVIEWER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
ACTIONS = ["respond_direct", "verify_then_respond"]


def subject(tenant: str = TENANT, user: str = USER) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user, tenant_id=tenant)


def reviewer() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=REVIEWER,
        tenant_id=TENANT,
        permissions=["intelligence.ml.verification_review"],
    )


def row(index: int, *, reward: float = 0.8, needed: bool = False) -> PolicyObservation:
    return PolicyObservation(
        observation_id=f"reviewed-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"frozen-features-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope=TENANT,
            eligible_actions=list(ACTIONS),
            risk_class=ActionRiskClass.LOW,
            normalized_features={"private": "DO_NOT_EXPOSE"},
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=ACTIONS[index % 2],
        behavior_policy_id="baseline-verification-policy",
        behavior_policy_version="1",
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        reward=reward,
        utility_policy_version="independent-review-v1",
        candidate_policy_id="shadow-candidate",
        candidate_policy_version="1",
        candidate_probabilities={ACTIONS[0]: 0.4, ACTIONS[1]: 0.6},
        metadata={
            "reward_evidence_type": "human_review",
            "reward_evidence_ref": f"kcm:review:reward:{index}",
            "verification_needed": needed,
            "verification_label_source": "human_review",
            "verification_label_ref": f"kcm:review:need:{index}",
            "raw_prompt": "DO_NOT_EXPOSE",
        },
    )


async def accepted(
    store: InMemoryOutcomeStore, entry: PolicyObservation
) -> None:
    await GovernedVerificationReviewEvidence(
        tenant_id=TENANT, subject_user_id=USER, store=store,
    ).record_review(entry, reviewer=reviewer())


@pytest.mark.asyncio
async def test_reviewed_decisions_are_real_user_scoped_not_certified_skills() -> None:
    store = InMemoryOutcomeStore()
    one, two = row(1, reward=0.8, needed=True), row(2, reward=0.6)
    await accepted(store, one)
    await accepted(store, two)
    projector = KcmReviewedDecisionProjector(store=store, max_decisions=5)
    original = deepcopy([one, two])
    result = await projector.inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[one, two],
    )
    assert result.health is KcmDecisionEvidenceHealth.VERIFIED
    assert result.domain == "verification_policy"
    assert result.evaluation_mode == "shadow"
    assert result.scope == "user"
    assert result.decision_count == 2
    assert result.reviewed_receipt_count == 4
    assert result.distinct_reviewer_count == 1
    assert result.mean_reviewed_reward == pytest.approx(0.7)
    assert result.judged_verification_needed_count == 1
    assert len(result.evidence_sha256) == 64
    assert result.reason_codes == ("task_specific_reviews_only", "not_skill_certification")
    assert result.capability_certified is False
    assert result.policy_activated is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert [one, two] == original
    assert "DO_NOT_EXPOSE" not in repr(result)


@pytest.mark.asyncio
async def test_duplicate_request_reordered_evidence_has_same_fingerprint() -> None:
    store = InMemoryOutcomeStore()
    one, two = row(11), row(12)
    await accepted(store, one)
    await accepted(store, two)
    service = KcmReviewedDecisionProjector(store=store, max_decisions=5)
    first = await service.inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[one, two],
    )
    second = await service.inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[two, one],
    )
    assert first.health is KcmDecisionEvidenceHealth.VERIFIED
    assert first.evidence_sha256 == second.evidence_sha256


@pytest.mark.asyncio
async def test_changed_reward_cannot_reuse_review_receipt() -> None:
    store = InMemoryOutcomeStore()
    entry = row(21)
    await accepted(store, entry)
    changed = deepcopy(entry)
    changed.reward = 1.0
    result = await KcmReviewedDecisionProjector(
        store=store, max_decisions=2,
    ).inspect(subject=subject(), tenant_id=TENANT, user_id=USER,
              observations=[changed])
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    assert result.mean_reviewed_reward is None
    assert result.decision_count == 0
    assert not result.capability_certified


@pytest.mark.asyncio
async def test_modified_policy_context_and_receipt_value_fail_closed() -> None:
    store = InMemoryOutcomeStore()
    entry = row(22)
    await accepted(store, entry)
    changed = deepcopy(entry)
    changed.context.feature_snapshot_id = "invented"
    projector = KcmReviewedDecisionProjector(store=store, max_decisions=2)
    result = await projector.inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[changed],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    store._records[0]["metadata"]["value"] = 0.1
    result = await projector.inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[entry],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_missing_and_deleted_receipts_do_not_report_partial_success() -> None:
    store = InMemoryOutcomeStore()
    one, two = row(31), row(32)
    await accepted(store, one)
    await accepted(store, two)
    store._records.pop()
    result = await KcmReviewedDecisionProjector(
        store=store, max_decisions=4,
    ).inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[one, two],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    assert result.reviewed_receipt_count == 0
    assert result.evidence_sha256 == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrong_subject,tenant,user",
    [
        (lambda: subject(OTHER_TENANT), TENANT, USER),
        (lambda: subject(TENANT, OTHER_USER), TENANT, USER),
        (lambda: subject(), OTHER_TENANT, USER),
        (lambda: subject(), TENANT, OTHER_USER),
        (lambda: AuthenticatedPrincipal(
            user_id=USER, tenant_id=TENANT,
            expires_at=datetime(2020, 1, 1),
        ), TENANT, USER),
        (lambda: {"user_id": USER, "tenant_id": TENANT}, TENANT, USER),
    ],
)
async def test_cross_principal_and_forged_auth_denied(
    wrong_subject, tenant: str, user: str,
) -> None:
    store = InMemoryOutcomeStore()
    await accepted(store, row(41))
    with pytest.raises(PermissionError):
        await KcmReviewedDecisionProjector(
            store=store, max_decisions=4,
        ).inspect(
            subject=wrong_subject(), tenant_id=tenant,
            user_id=user, observations=[row(41)],
        )


@pytest.mark.asyncio
async def test_other_authenticated_user_cannot_read_existing_reviews() -> None:
    store = InMemoryOutcomeStore()
    await accepted(store, row(42))
    result = await KcmReviewedDecisionProjector(
        store=store, max_decisions=4,
    ).inspect(
        subject=subject(TENANT, OTHER_USER), tenant_id=TENANT,
        user_id=OTHER_USER, observations=[row(42)],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    assert result.mean_reviewed_reward is None


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [[], [None], ["not-an-observation"], [None] * 5])
async def test_empty_invalid_and_overbudget_batch_fail_closed(entries) -> None:
    result = await KcmReviewedDecisionProjector(
        store=InMemoryOutcomeStore(), max_decisions=3,
    ).inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=entries,
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    assert "decision_evidence_budget_or_type_invalid" in result.reason_codes


@pytest.mark.asyncio
async def test_same_decision_twice_is_not_two_samples() -> None:
    store = InMemoryOutcomeStore()
    entry = row(50)
    await accepted(store, entry)
    result = await KcmReviewedDecisionProjector(
        store=store, max_decisions=3,
    ).inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[entry, entry],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    assert not result.capability_certified


@pytest.mark.asyncio
async def test_unsupported_risk_and_self_report_cannot_verify() -> None:
    store = InMemoryOutcomeStore()
    entry = row(61)
    entry.context.risk_class = ActionRiskClass.HIGH
    result = await KcmReviewedDecisionProjector(
        store=store, max_decisions=3,
    ).inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[entry],
    )
    assert result.health is KcmDecisionEvidenceHealth.UNAVAILABLE
    other = row(62)
    other.metadata["verification_label_source"] = "model_self_report"
    second = await KcmReviewedDecisionProjector(
        store=store, max_decisions=3,
    ).inspect(
        subject=subject(), tenant_id=TENANT, user_id=USER,
        observations=[other],
    )
    assert second.health is KcmDecisionEvidenceHealth.UNAVAILABLE


def test_budget_requires_explicit_valid_limit() -> None:
    for value in (0, -1, 501, True, None, 1.5):
        with pytest.raises(ValueError, match="budget"):
            KcmReviewedDecisionProjector(
                store=InMemoryOutcomeStore(), max_decisions=value,
            )
