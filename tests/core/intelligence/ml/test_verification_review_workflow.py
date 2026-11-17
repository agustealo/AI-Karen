"""KCOG-01B9: review issuance is backed by real recorded runtime lineage.

Fixtures are synthetic and use in-memory implementations of the *existing*
TrajectoryStore and OutcomeStore contracts. The dedicated PostgreSQL CI gate
separately exercises the canonical real database.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ai_karen_engine.core.intelligence.ml.verification_review_workflow import (
    ReviewJudgement,
    VerificationReviewWorkflow,
)
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore,
    OutcomeStoreError,
)
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionObservation,
    FeatureSnapshot,
)
from ai_karen_engine.core.runtime.trajectory.store import (
    InMemoryTrajectoryStore,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal


TENANT = str(uuid4())
OTHER_TENANT = str(uuid4())
SUBJECT = str(uuid4())
OTHER_USER = str(uuid4())
REVIEWER = str(uuid4())
PERMISSION = "intelligence.ml.verification_review"
ACTIONS = ("respond_direct", "verify_then_respond")


def principal(*, user=REVIEWER, tenant=TENANT, permissions=None):
    if permissions is None:
        permissions = [PERMISSION]
    return AuthenticatedPrincipal(
        user_id=user, tenant_id=tenant, permissions=permissions,
    )


def lineage(*, tenant=TENANT, subject=SUBJECT, index=1):
    recorded = DecisionObservation(
        decision_observation_id=f"proof-decision-{index}",
        trajectory_id=f"runtime-trajectory-{index}",
        feature_snapshot_id=f"runtime-features-{index}",
        decision_type="respond_strategy",
        behavior_policy_id="runtime-verification-policy",
        behavior_policy_version="v2",
        candidate_actions=ACTIONS,
        eligible_actions=ACTIONS,
        chosen_action=ACTIONS[0],
        created_at=datetime.now(timezone.utc),
        chosen_probability=0.5,
        action_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5},
        ope_eligible=True,
        tenant_id=tenant,
        user_id=subject,
        metadata={
            "verification_policy_snapshot": {
                "schema_version": "verification_policy_snapshot_v1",
                "candidate_policy_id": "candidate-frozen",
                "candidate_policy_version": "v9",
                "candidate_probabilities": {
                    ACTIONS[0]: 0.25,
                    ACTIONS[1]: 0.75,
                },
                "risk_class": "low",
                "utility_policy_version": "independent-review-v1",
            }
        },
    )
    features = FeatureSnapshot(
        feature_snapshot_id=recorded.feature_snapshot_id,
        trajectory_id=recorded.trajectory_id,
        tenant_id=tenant,
        user_id=subject,
        request_id=f"request-{index}",
        correlation_id=f"corr-{index}",
        feature_version="features-v1",
        created_at=datetime.now(timezone.utc),
        metadata={
            "prompt": "NEVER_PERSIST_PROMPT",
            "policy_decision_id": f"runtime-policy-{index}",
        },
    )
    return recorded, features


def case(*, recorded=None, features=None):
    stored, snapshot = lineage()
    stored = recorded if recorded is not None else stored
    snapshot = features if features is not None else snapshot
    decisions = InMemoryTrajectoryStore()
    decisions.save_feature_snapshot(snapshot)
    decisions.save_decision_observation(stored)
    # This fixture models a genuinely completed selected strategy. Review
    # admission must read these *independently stored* runtime observations
    # rather than derive them from the externally supplied review judgement.
    trajectory = ExecutionTrajectory(
        trajectory_id=stored.trajectory_id,
        tenant_id=TENANT,
        user_id=SUBJECT,
        request_id=snapshot.request_id,
        correlation_id=snapshot.correlation_id,
        session_id="review-session",
        conversation_id="review-conversation",
        executed_topology="direct",
        policy_decision_id=f"runtime-policy-1",
        execution_status="success",
        completed_at=datetime.now(timezone.utc),
        actual_provider="ollama-local",
        actual_model="measured-installed-model",
        fallback_level=0,
        degraded_mode=False,
        response_source="model",
    )
    decisions.save(trajectory)
    receipts = InMemoryOutcomeStore()
    receipts.save_outcome({
        "outcome_id": "test-runtime-selected-1",
        "source": "runtime.execution",
        "trajectory_id": trajectory.trajectory_id,
        "decision_observation_id": stored.decision_observation_id,
        "tenant_id": TENANT,
        "user_id": SUBJECT,
        "request_id": snapshot.request_id,
        "correlation_id": snapshot.correlation_id,
        "session_id": trajectory.session_id,
        "conversation_id": trajectory.conversation_id,
        "status": "success",
        "response_completed": True,
        "persistence_success": True,
        "fallback_count": 0,
        "metadata": {
            "transcript_persistence_status": "persisted",
            "actual_provider": trajectory.actual_provider,
            "actual_model": trajectory.actual_model,
            "model_calls": 1,
            "tool_calls": 0,
            "selected_strategy_execution": {
                "schema_version": "selected_strategy_execution_v1",
                "selected_action": "respond_direct",
                "policy_decision_id": trajectory.policy_decision_id,
                "policy_version": "v2",
                "status": "selected_runtime_path_observed",
                "provider_receipt_observed": True,
                "response_completed": True,
                "transcript_durable": True,
                "actual_provider": trajectory.actual_provider,
                "actual_model": trajectory.actual_model,
                "execution_observation_only": True,
                "independent_verification_proven": False,
                "dual_action_eligibility_established": False,
                "randomized_selection": False,
                "ope_eligible": False,
            },
        },
    })
    handler = VerificationReviewWorkflow(
        lineage_store=decisions, outcome_store=receipts,
    )
    judgement = ReviewJudgement(
        decision_observation_id=stored.decision_observation_id,
        subject_user_id=SUBJECT,
        reward=0.8,
        verification_needed=True,
    )
    return handler, judgement, receipts, stored, decisions


@pytest.mark.asyncio
async def test_authenticated_independent_review_uses_only_frozen_runtime_lineage():
    handler, judgement, receipts, decision, _ = case()
    original = deepcopy(decision)
    result = await handler.submit(judgement, reviewer=principal(), correlation_id="corr")
    assert result == {
        "stored": True,
        "receipt_count": 2,
        "evidence_schema": "ml_verification_review_v1",
        "decision_observation_id": decision.decision_observation_id,
        "evaluation_mode": "shadow",
        "policy_activated": False,
        "decision_provenance": "durable_runtime_lineage",
    }
    persisted = receipts.list_for_tenant(
        TENANT, user_id=SUBJECT, source="intelligence.ml",
    )
    assert len(persisted) == 2
    assert decision == original
    assert "NEVER_PERSIST_PROMPT" not in str(persisted)
    assert all(row["metadata"]["reviewer_user_id"] == REVIEWER for row in persisted)
    assert all(row["metadata"]["observation_sha256"] for row in persisted)
    assert all(row["metadata"]["utility_policy_version"] == "independent-review-v1"
               for row in persisted)
    assert all(row["metadata"]["schema_version"] == "ml_verification_review_v1"
               for row in persisted)
    with pytest.raises(OutcomeStoreError):
        await handler.submit(
            replace(judgement, reward=0.1, verification_needed=False),
            reviewer=principal(),
        )
    assert len(receipts.list_for_tenant(TENANT, source="intelligence.ml")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,denial", [
    (lambda: principal(user=SUBJECT), PermissionError),
    # Tenant-RLS lookup must not disclose that another tenant has a decision.
    (lambda: principal(tenant=OTHER_TENANT), LookupError),
    (lambda: principal(permissions=[]), PermissionError),
    (lambda: {"user_id": REVIEWER, "tenant_id": TENANT,
              "permissions": [PERMISSION]}, PermissionError),
])
async def test_untrusted_cross_tenant_and_self_reviewers_cannot_issue(actor, denial):
    handler, judgement, receipts, _, _ = case()
    with pytest.raises(denial):
        await handler.submit(judgement, reviewer=actor())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
async def test_missing_decision_and_wrong_subject_do_not_leak_or_write():
    handler, judgement, receipts, _, _ = case()
    with pytest.raises(LookupError):
        await handler.submit(
            replace(judgement, decision_observation_id="never-existed"),
            reviewer=principal(),
        )
    with pytest.raises(LookupError):
        await handler.submit(
            replace(judgement, subject_user_id=OTHER_USER),
            reviewer=principal(),
        )
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate,exc", [
    (
        lambda obj: replace(obj, ope_eligible=False),
        ValueError,
    ),
    (
        lambda obj: replace(obj, chosen_probability=0.9),
        ValueError,
    ),
    (
        lambda obj: replace(obj, chosen_probability=float("nan")),
        ValueError,
    ),
    (
        lambda obj: replace(
            obj,
            action_probabilities={ACTIONS[0]: 0.2, ACTIONS[1]: 0.2},
        ),
        ValueError,
    ),
    (
        lambda obj: replace(
            obj,
            action_probabilities={ACTIONS[0]: 0.5, ACTIONS[1]: 0.5, "illegal": 0.0},
        ),
        ValueError,
    ),
    (
        lambda obj: replace(obj, decision_type="provider_selection"),
        ValueError,
    ),
    (
        lambda obj: replace(obj, chosen_action="unrecorded"),
        ValueError,
    ),
    (
        lambda obj: replace(obj, user_id=OTHER_USER),
        LookupError,
    ),
    (
        lambda obj: replace(obj, metadata={}),
        ValueError,
    ),
    (
        lambda obj: replace(
            obj, metadata={"verification_policy_snapshot": {
                **obj.metadata["verification_policy_snapshot"],
                "risk_class": "high",
            }},
        ),
        PermissionError,
    ),
    (
        lambda obj: replace(
            obj, metadata={"verification_policy_snapshot": {
                **obj.metadata["verification_policy_snapshot"],
                "candidate_probabilities": {},
            }},
        ),
        ValueError,
    ),
])
async def test_wrong_or_incomplete_logged_decisions_cannot_be_reviewed(mutate, exc):
    recorded, features = lineage()
    handler, judgement, receipts, _, _ = case(
        recorded=mutate(recorded), features=features,
    )
    with pytest.raises(exc):
        await handler.submit(judgement, reviewer=principal())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
async def test_feature_snapshot_must_match_exact_subject_tenant_and_trajectory():
    recorded, features = lineage()
    for tampered in (
        replace(features, tenant_id=OTHER_TENANT),
        replace(features, user_id=OTHER_USER),
        replace(features, trajectory_id="other-trajectory"),
        replace(features, feature_snapshot_id="other-id"),
    ):
        handler, judgement, receipts, _, _ = case(
            recorded=recorded, features=tampered,
        )
        with pytest.raises((PermissionError, ValueError)):
            await handler.submit(judgement, reviewer=principal())
        assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


def test_review_input_requires_bounded_independent_labels():
    default = ReviewJudgement(
        decision_observation_id="decision-1",
        subject_user_id=SUBJECT,
        reward=0.2,
        verification_needed=False,
    )
    default.validate()
    for mutation in (
        replace(default, reward=float("nan")),
        replace(default, reward=float("inf")),
        replace(default, reward=-0.1),
        replace(default, reward=True),
        replace(default, verification_needed="yes"),
        replace(default, decision_observation_id="../bad?query"),
    ):
        with pytest.raises(ValueError):
            mutation.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_status", "cancelled"),
        ("execution_status", "failure"),
        ("execution_status", None),
        ("completed_at", None),
        ("tenant_id", OTHER_TENANT),
        ("user_id", OTHER_USER),
        ("request_id", "unrelated-request"),
        ("correlation_id", "unrelated-correlation"),
        ("policy_decision_id", "unrelated-policy"),
        ("error_code", "CHAT_REQUEST_CANCELLED"),
        ("actual_provider", None),
        ("actual_model", None),
        ("degraded_mode", True),
        ("degraded_mode", None),
        ("fallback_level", 1),
        ("fallback_level", None),
        ("executed_topology", "reasoning"),
    ],
)
async def test_b2c3a_reviewer_refuses_unverified_or_incomplete_execution_trajectory(
    field, value,
):
    handler, judgement, receipts, observed, lineage_store = case()
    trajectory = lineage_store.get(observed.trajectory_id, tenant_id=TENANT)
    assert trajectory is not None
    setattr(trajectory, field, value)
    with pytest.raises(ValueError, match="Completed selected runtime trajectory"):
        await handler.submit(judgement, reviewer=principal())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata_path,value",
    [
        (("status",), "failure"),
        (("response_completed",), False),
        (("persistence_success",), False),
        (("fallback_count",), 1),
        (("user_id",), OTHER_USER),
        (("tenant_id",), OTHER_TENANT),
        (("request_id",), "unrelated-request"),
        (("correlation_id",), "unrelated-correlation"),
        (("session_id",), "other-session"),
        (("conversation_id",), "other-conversation"),
        (("decision_observation_id",), "other-decision"),
        (("metadata", "transcript_persistence_status"), "failed"),
        (("metadata", "actual_provider"), "invented"),
        (("metadata", "actual_model"), "invented"),
        (("metadata", "model_calls"), 0),
        (("metadata", "tool_calls"), 1),
        (("metadata", "selected_strategy_execution", "schema_version"), "other"),
        (("metadata", "selected_strategy_execution", "selected_action"), "verify_then_respond"),
        (("metadata", "selected_strategy_execution", "policy_decision_id"), "other"),
        (("metadata", "selected_strategy_execution", "policy_version"), "other"),
        (("metadata", "selected_strategy_execution", "status"), "unverified"),
        (("metadata", "selected_strategy_execution", "provider_receipt_observed"), False),
        (("metadata", "selected_strategy_execution", "transcript_durable"), False),
        (("metadata", "selected_strategy_execution", "response_completed"), False),
        (("metadata", "selected_strategy_execution", "actual_provider"), "invented"),
        (("metadata", "selected_strategy_execution", "actual_model"), "invented"),
        (("metadata", "selected_strategy_execution", "independent_verification_proven"), True),
        (("metadata", "selected_strategy_execution", "ope_eligible"), True),
        (("metadata", "selected_strategy_execution", "randomized_selection"), True),
    ],
)
async def test_b2c3a_reviewer_refuses_forged_execution_outcome_receipts(
    metadata_path, value,
):
    handler, judgement, receipts, _, _ = case()
    observed = receipts._records[0]  # In-memory test fixture only.
    target = observed
    for part in metadata_path[:-1]:
        target = target[part]
    target[metadata_path[-1]] = value
    with pytest.raises(ValueError, match="(selected execution receipt|Exactly one selected execution)"):
        await handler.submit(judgement, reviewer=principal())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["missing_trajectory", "missing_receipt", "duplicate_receipt", "missing_policy_bind"])
async def test_b2c3a_review_requires_unique_real_scoped_runtime_evidence(scenario):
    handler, judgement, receipts, recorded, decisions = case()
    if scenario == "missing_trajectory":
        decisions._records.clear()
    elif scenario == "missing_receipt":
        receipts._records.clear()
    elif scenario == "duplicate_receipt":
        receipts.save_outcome({
            **receipts._records[0],
            "outcome_id": "different-outcome-id",
        })
    else:
        feature = decisions.get_feature_snapshot(
            recorded.feature_snapshot_id, tenant_id=TENANT,
        )
        assert feature is not None
        feature.metadata.pop("policy_decision_id")
    with pytest.raises(ValueError):
        await handler.submit(judgement, reviewer=principal())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []


@pytest.mark.asyncio
async def test_b2c3a_selected_execution_readback_storage_error_cannot_create_label():
    handler, judgement, receipts, _, _ = case()

    def unavailable(*args, **kwargs):
        raise OutcomeStoreError("readback backend unavailable")

    receipts.get_for_trajectory = unavailable
    with pytest.raises(OutcomeStoreError):
        await handler.submit(judgement, reviewer=principal())
    assert receipts.list_for_tenant(TENANT, source="intelligence.ml") == []
