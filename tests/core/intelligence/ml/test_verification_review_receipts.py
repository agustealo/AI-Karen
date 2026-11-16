"""KCOG-01B7: reviewer-authorized, durable policy observation evidence.

Uses InMemoryOutcomeStore solely as an isolated adapter test. The production
path uses the existing PostgreSQL RLS, unique outcome IDs and atomic writes.
These synthetic labels do not establish real-world reasoning improvement.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

import pytest
from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyObservation,
)
from ai_karen_engine.core.intelligence.ml.verification_policy_evaluation import (
    evaluate_verification_effort_candidate,
    evaluate_verification_effort_with_durable_reviews,
)
from ai_karen_engine.core.intelligence.ml.verification_review_evidence import (
    GovernedVerificationReviewEvidence,
)
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore,
    OutcomeStoreError,
    PostgresOutcomeStore,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SUBJECT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
REVIEWER = "dddddddd-dddd-dddd-dddd-dddddddddddd"
OTHER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
PERMISSION = "intelligence.ml.verification_review"


@dataclass
class PrincipalFixture:
    """Test the trusted principal contract without importing the HTTP stack."""

    user_id: str
    tenant_id: str
    permissions: list[str] = field(default_factory=list)
    expires_at: datetime | None = None

    def has_permission(self, permission: str) -> bool:
        return permission.lower() in {item.lower() for item in self.permissions}

    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() > self.expires_at


ACTIONS = ["respond_direct", "verify_then_respond"]
BASELINE = SimpleNamespace(policy_id="baseline-v1", policy_version="v1")
CANDIDATE = SimpleNamespace(policy_id="shadow-v1", policy_version="v1")


def subject(tenant: str = TENANT, user_id: str = SUBJECT):
    return PrincipalFixture(user_id=user_id, tenant_id=tenant)


def reviewer(
    *, tenant: str = TENANT, user_id: str = REVIEWER, allowed: bool = True,
):
    return PrincipalFixture(
        user_id=user_id, tenant_id=tenant,
        permissions=[PERMISSION] if allowed else [],
    )


def observation(idx: int, *, needed: bool = False):
    chosen = ACTIONS[idx % 2]
    return PolicyObservation(
        observation_id=f"review-case-{idx}",
        context=PolicyContext(
            feature_snapshot_id=f"frozen-features-{idx}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope=TENANT,
            eligible_actions=list(ACTIONS),
            risk_class=ActionRiskClass.LOW,
            normalized_features={"secret": "MUST_NOT_BE_PERSISTED"},
        ),
        eligible_actions=list(ACTIONS),
        chosen_action=chosen,
        behavior_policy_id=BASELINE.policy_id,
        behavior_policy_version=BASELINE.policy_version,
        behavior_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        reward=0.8,
        utility_policy_version="independent-review-v1",
        candidate_policy_id=CANDIDATE.policy_id,
        candidate_policy_version=CANDIDATE.policy_version,
        candidate_probabilities={ACTIONS[0]: 0.4, ACTIONS[1]: 0.6},
        metadata={
            "reward_evidence_type": "human_review",
            "reward_evidence_ref": f"judge:reward:{idx}",
            "verification_needed": needed,
            "verification_label_source": "human_review",
            "verification_label_ref": f"judge:need:{idx}",
            "raw_prompt": "MUST_NOT_BE_PERSISTED",
        },
    )


def service(store, *, tenant=TENANT, user=SUBJECT):
    return GovernedVerificationReviewEvidence(
        tenant_id=tenant, subject_user_id=user, store=store,
    )


@pytest.mark.asyncio
async def test_receipts_are_atomic_durable_scoped_and_redacted():
    store = InMemoryOutcomeStore()
    entry = observation(1, needed=True)
    original = deepcopy(entry)
    issued = await service(store).record_review(entry, reviewer=reviewer())
    assert issued["stored"] is True
    assert issued["receipt_count"] == 2
    assert entry == original
    persisted = store.list_for_tenant(
        TENANT, user_id=SUBJECT, source="intelligence.ml",
    )
    assert len(persisted) == 2
    assert {row["outcome_id"] for row in persisted} == {
        "judge:reward:1", "judge:need:1",
    }
    assert "MUST_NOT_BE_PERSISTED" not in str(persisted)
    assert all(row["metadata"]["reviewer_user_id"] == REVIEWER for row in persisted)
    assert all(
        PostgresOutcomeStore._validated_identity(row)
        == (TENANT, "intelligence.ml") for row in persisted
    )
    proof = await service(store).require_persisted_reviews(
        [entry], subject=subject(),
    )
    assert proof == {
        "evidence_schema": "ml_verification_review_v1",
        "persisted_decision_count": 1,
        "persisted_receipt_count": 2,
        "reviewer_count": 1,
        "receipt_scope_verified": True,
        "policy_activated": False,
    }
    # A separately constructed reader must still retrieve durable records.
    assert (
        await service(store).require_persisted_reviews(
            [entry], subject=subject(),
        )
    ) == proof


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_reviewer",
    [
        lambda: reviewer(allowed=False),
        lambda: reviewer(tenant=OTHER_TENANT),
        lambda: reviewer(user_id=SUBJECT),
        lambda: subject(),
        lambda: "forged-actor",
        lambda: PrincipalFixture(
            user_id=REVIEWER, tenant_id=TENANT, permissions=[PERMISSION],
            expires_at=datetime(2020, 1, 1),
        ),
    ],
)
async def test_unprivileged_self_cross_tenant_and_expired_issuers_denied(invalid_reviewer):
    store = InMemoryOutcomeStore()
    with pytest.raises(PermissionError):
        await service(store).record_review(
            observation(3), reviewer=invalid_reviewer(),
        )
    assert store.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
async def test_duplicate_receipt_replay_is_strict_and_atomic():
    store = InMemoryOutcomeStore()
    first = observation(1)
    await service(store).record_review(first, reviewer=reviewer())
    with pytest.raises(OutcomeStoreError, match="duplicate|Duplicate"):
        await service(store).record_review(first, reviewer=reviewer())
    second = observation(2)
    second.metadata["reward_evidence_ref"] = first.metadata["reward_evidence_ref"]
    with pytest.raises(OutcomeStoreError):
        await service(store).record_review(second, reviewer=reviewer())
    assert len(store.list_for_tenant(TENANT, source="intelligence.ml")) == 2


@pytest.mark.asyncio
async def test_missing_or_tampered_receipt_fails_closed():
    entry = observation(4)
    store = InMemoryOutcomeStore()
    await service(store).record_review(entry, reviewer=reviewer())
    store._records.pop()
    with pytest.raises(OutcomeStoreError, match="Incomplete"):
        await service(store).require_persisted_reviews(
            [entry], subject=subject(),
        )

    store = InMemoryOutcomeStore()
    await service(store).record_review(entry, reviewer=reviewer())
    store._records[0]["metadata"]["value"] = 0.2
    with pytest.raises(OutcomeStoreError, match="does not match"):
        await service(store).require_persisted_reviews(
            [entry], subject=subject(),
        )


@pytest.mark.asyncio
async def test_mutated_policy_or_ground_truth_cannot_reuse_old_review():
    store = InMemoryOutcomeStore()
    entry = observation(9, needed=True)
    await service(store).record_review(entry, reviewer=reviewer())
    for mutation in (
        lambda x: setattr(x, "reward", 0.1),
        lambda x: x.candidate_probabilities.update({
            ACTIONS[0]: 0.7, ACTIONS[1]: 0.3,
        }),
        lambda x: setattr(x.context, "feature_snapshot_id", "changed"),
        lambda x: x.metadata.update(verification_needed=False),
        lambda x: setattr(x, "candidate_policy_version", "v2"),
    ):
        altered = deepcopy(entry)
        mutation(altered)
        with pytest.raises(OutcomeStoreError, match="does not match"):
            await service(store).require_persisted_reviews(
                [altered], subject=subject(),
            )


@pytest.mark.asyncio
async def test_subject_scoping_blocks_other_user_tenant_and_expired_read():
    store = InMemoryOutcomeStore()
    entry = observation(10)
    await service(store).record_review(entry, reviewer=reviewer())
    for wrong in (
        subject(OTHER_TENANT), subject(TENANT, OTHER),
        PrincipalFixture(
            user_id=SUBJECT, tenant_id=TENANT,
            expires_at=datetime(2020, 1, 1),
        ),
    ):
        with pytest.raises(PermissionError):
            await service(store).require_persisted_reviews(
                [entry], subject=wrong,
            )

    # Direct store lookup is still scoped: never reveal another principal's data.
    assert store.list_scoped_outcomes_by_ids(
        TENANT, user_id=OTHER, source="intelligence.ml",
        outcome_ids=["judge:reward:10", "judge:need:10"],
    ) == []
    assert store.list_scoped_outcomes_by_ids(
        OTHER_TENANT, user_id=SUBJECT, source="intelligence.ml",
        outcome_ids=["judge:reward:10", "judge:need:10"],
    ) == []


@pytest.mark.asyncio
async def test_direct_metadata_only_study_never_claims_durable_review():
    entry = observation(0)
    unverified = evaluate_verification_effort_candidate(
        [entry], tenant_id=TENANT,
        baseline_policy=BASELINE, candidate_policy=CANDIDATE,
    )
    assert unverified["durable_review_receipts_verified"] is False
    assert unverified["policy_activated"] is False


@pytest.mark.asyncio
async def test_reviewed_shadow_study_uses_durable_source_not_app_claim():
    store = InMemoryOutcomeStore()
    rows = [observation(i, needed=bool(i % 3)) for i in range(100)]
    for item in rows:
        await service(store).record_review(item, reviewer=reviewer())
    report = await evaluate_verification_effort_with_durable_reviews(
        rows, subject=subject(), baseline_policy=BASELINE,
        candidate_policy=CANDIDATE, store=store,
    )
    assert report["durable_review_receipts_verified"] is True
    assert report["durable_review_provenance"]["persisted_receipt_count"] == 200
    assert report["durable_review_provenance"]["persisted_decision_count"] == 100
    assert report["policy_activated"] is False
    assert report["runtime_policy_approval_required"] is True
    assert report["promotion_decision"] != "promotion_eligible"
    assert "ips" in report["estimates"]

    missing = InMemoryOutcomeStore()
    with pytest.raises(OutcomeStoreError, match="Incomplete"):
        await evaluate_verification_effort_with_durable_reviews(
            rows, subject=subject(), baseline_policy=BASELINE,
            candidate_policy=CANDIDATE, store=missing,
        )


@pytest.mark.asyncio
async def test_high_risk_and_untrusted_source_never_issued():
    store = InMemoryOutcomeStore()
    row = observation(11)
    row.context.risk_class = ActionRiskClass.HIGH
    with pytest.raises(ValueError):
        await service(store).record_review(row, reviewer=reviewer())

    row = observation(12)
    row.metadata["verification_label_source"] = "model_self_report"
    with pytest.raises(ValueError):
        await service(store).record_review(row, reviewer=reviewer())

    assert store.list_for_tenant(TENANT, source="intelligence.ml") == []


def test_canonical_store_rejects_forged_or_extra_verification_fields():
    bad = {
        "outcome_id": "judge:need:1",
        "tenant_id": TENANT, "user_id": SUBJECT,
        "source": "intelligence.ml",
        "decision_observation_id": "review-case-1",
        "metadata": {
            "schema_version": "ml_verification_review_v1",
            "evidence_kind": "verification_need",
            "evidence_source": "human_review",
            "evidence_ref": "judge:need:1",
            "decision_observation_id": "review-case-1",
            "observation_sha256": "0" * 64,
            "reviewer_user_id": REVIEWER,
            "utility_policy_version": "independent-review-v1",
            "value": True,
        },
    }
    assert PostgresOutcomeStore._validated_identity(bad) == (
        TENANT, "intelligence.ml",
    )
    for changed in (
        {**bad, "outcome_id": "different"},
        {**bad, "user_id": REVIEWER},
        {**bad, "metadata": {**bad["metadata"], "secret": "danger"}},
        {**bad, "metadata": {**bad["metadata"], "value": "true"}},
        {**bad, "metadata": {**bad["metadata"], "observation_sha256": "fake"}},
    ):
        with pytest.raises(OutcomeStoreError, match="independently issued"):
            PostgresOutcomeStore._validated_identity(changed)


def test_scoped_batch_lookup_requires_strict_user_tenant_and_distinct_ids():
    store = InMemoryOutcomeStore()
    for inputs in (
        {"user_id": "", "outcome_ids": ["1"]},
        {"user_id": SUBJECT, "outcome_ids": []},
        {"user_id": SUBJECT, "outcome_ids": ["1", "1"]},
        {"user_id": SUBJECT, "outcome_ids": [""]},
    ):
        with pytest.raises(OutcomeStoreError):
            store.list_scoped_outcomes_by_ids(
                TENANT, source="intelligence.ml", **inputs,
            )
