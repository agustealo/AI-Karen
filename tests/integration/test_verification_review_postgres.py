"""KCOG-01B8: REAL PostgreSQL review receipt acceptance on a disposable DB only.

No monkeypatched transaction scopes, in-memory outcome stores, or synthetic
successful persistence. This exercises the canonical PostgreSQL OutcomeStore
against its production outcome-ledger migrations with isolated FK prerequisites.

To run:
    KAREN_TEST_REVIEW_DATABASE_URL=postgresql://.../karen_review_test \
    DATABASE_URL=postgresql://.../karen_review_test \
    pytest tests/integration/test_verification_review_postgres.py -q

Never run against a non-disposable database.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
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
from ai_karen_engine.core.intelligence.ml.verification_review_workflow import (
    ReviewJudgement,
    VerificationReviewWorkflow,
)
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionObservation,
    FeatureSnapshot,
)
from ai_karen_engine.core.runtime.trajectory.store import PostgresTrajectoryStore
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.policy import PolicyEvaluationRequest, RuntimePolicyEnforcer
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStoreError,
    PostgresOutcomeStore,
)
from ai_karen_engine.core.runtime.contracts import (
    ResponseProvenance,
    ResponseSource,
)
from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    reset_correlation_context,
    set_correlation_context,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal


_ACTIONS = ["respond_direct", "verify_then_respond"]
_PERMISSION = "intelligence.ml.verification_review"
_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = (
    "20261003010000_20_runtime_outcome_evidence.sql",
    "20261019020000_37_intelligence_ml_outcome_evidence.sql",
    "20261006010000_24_learning_decision_lineage.sql",
)


def _disposable_dsn() -> str:
    dsn = os.environ.get("KAREN_TEST_REVIEW_DATABASE_URL", "")
    if not dsn:
        pytest.skip("No disposable PostgreSQL review database configured")
    normalized = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.path != "/karen_review_test"
        or not parsed.username
        or os.environ.get("DATABASE_URL") != dsn
    ):
        pytest.fail(
            "Refusing real review-receipt proof outside the designated "
            "local disposable karen_review_test database"
        )
    return normalized


def _principal(user: str, tenant: str, *, reviewer: bool = False) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user,
        tenant_id=tenant,
        permissions=[_PERMISSION] if reviewer else [],
    )


def _observation(index: int, tenant: str) -> PolicyObservation:
    chosen = _ACTIONS[index % 2]
    return PolicyObservation(
        observation_id=f"pg-reviewed-decision-{index}",
        context=PolicyContext(
            feature_snapshot_id=f"pg-snapshot-{index}",
            decision_type=DecisionType.RESPOND_STRATEGY,
            tenant_scope=tenant,
            eligible_actions=list(_ACTIONS),
            risk_class=ActionRiskClass.LOW,
            normalized_features={"secret": "NEVER_PERSIST_REVIEW_PROMPT"},
        ),
        eligible_actions=list(_ACTIONS),
        chosen_action=chosen,
        behavior_policy_id="pg-baseline",
        behavior_policy_version="v1",
        behavior_probabilities={_ACTIONS[0]: 0.5, _ACTIONS[1]: 0.5},
        chosen_probability=0.5,
        candidate_policy_id="pg-shadow",
        candidate_policy_version="v1",
        candidate_probabilities={_ACTIONS[0]: 0.25, _ACTIONS[1]: 0.75},
        reward=0.75,
        utility_policy_version="pg-independent-review-v1",
        metadata={
            "reward_evidence_type": "human_review",
            "reward_evidence_ref": f"pg:reward:{index}",
            "verification_label_source": "human_review",
            "verification_label_ref": f"pg:needed:{index}",
            "verification_needed": bool(index % 2),
            "raw_prompt": "NEVER_PERSIST_REVIEW_PROMPT",
        },
    )


async def _prepare_disposable_database(raw: asyncpg.Connection) -> None:
    """Use actual ledger migrations; only FK prerequisite tables are scoped fixtures."""
    assert await raw.fetchval("SELECT current_database()") == "karen_review_test"
    await raw.execute(
        """
        CREATE TABLE public.tenants (id uuid PRIMARY KEY);
        CREATE TABLE public.auth_users (
            user_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES public.tenants(id)
        );
        """
    )
    for name in _MIGRATIONS:
        sql = (_ROOT / "supabase" / "migrations" / name).read_text()
        await raw.execute(sql)
    for table_name in ("outcome_records", "execution_trajectories"):
        state = await raw.fetchrow(
            """SELECT relrowsecurity, relforcerowsecurity
               FROM pg_class WHERE oid=to_regclass($1)""",
            f"public.{table_name}",
        )
        assert state is not None
        assert state["relrowsecurity"] and state["relforcerowsecurity"]
    policy = await raw.fetchval(
        """SELECT count(*) FROM pg_policies
           WHERE schemaname='public' AND tablename='outcome_records'
             AND policyname='outcome_records_tenant_scope'"""
    )
    assert policy == 1
    trajectory_policy = await raw.fetchval(
        """SELECT count(*) FROM pg_policies
           WHERE schemaname='public' AND tablename='execution_trajectories'
             AND policyname='execution_trajectories_tenant_scope'"""
    )
    assert trajectory_policy == 1
    await raw.execute(
        """
        CREATE ROLE karen_review_ci_reader NOLOGIN;
        GRANT USAGE ON SCHEMA public TO karen_review_ci_reader;
        GRANT SELECT, INSERT ON public.outcome_records TO karen_review_ci_reader;
        GRANT SELECT, INSERT ON public.execution_trajectories TO karen_review_ci_reader;
        """
    )


async def _assert_rls_is_real(
    raw: asyncpg.Connection,
    *,
    tenant_a: str,
    tenant_b: str,
    receipt_id: str,
    subject_id: str,
) -> None:
    """Prove tenant isolation with a non-superuser without BYPASSRLS privilege."""
    async with raw.transaction():
        await raw.execute("SET LOCAL ROLE karen_review_ci_reader")
        await raw.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)", tenant_b
        )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records WHERE outcome_id=$1",
            receipt_id,
        ) == 0
        # WITH CHECK must prohibit an attempted insert of the other tenant.
        # A savepoint allows the outer audit transaction to continue.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with raw.transaction():
                await raw.execute(
                    """
                    INSERT INTO public.outcome_records
                      (outcome_id, tenant_id, user_id, source, payload)
                    VALUES ($1, $2, $3, 'intelligence.ml', '{}'::jsonb)
                    """,
                    "rls-forbidden-cross-tenant", uuid.UUID(tenant_a),
                    uuid.UUID(subject_id),
                )
        await raw.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)", tenant_a
        )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records WHERE outcome_id=$1",
            receipt_id,
        ) == 1


@pytest.mark.asyncio
async def _assert_cancelled_trajectory_rls_is_real(
    raw: asyncpg.Connection,
    *,
    tenant_a: str,
    tenant_b: str,
    trajectory_id: str,
    subject_id: str,
) -> None:
    """Verify database FORCE RLS, not merely application's tenant predicates."""
    async with raw.transaction():
        await raw.execute("SET LOCAL ROLE karen_review_ci_reader")
        await raw.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)",
            tenant_b,
        )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.execution_trajectories "
            "WHERE trajectory_id=$1",
            trajectory_id,
        ) == 0
        # The same non-bypass reader has INSERT grants. Only the canonical
        # RLS WITH CHECK may reject writing another tenant's execution.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with raw.transaction():
                await raw.execute(
                    """INSERT INTO public.execution_trajectories
                       (trajectory_id, tenant_id, user_id, started_at, payload)
                       VALUES ($1, $2, $3, now(), '{}'::jsonb)""",
                    "pg-rls-forbidden-cross-tenant-cancel",
                    uuid.UUID(tenant_a),
                    uuid.UUID(subject_id),
                )
        await raw.execute(
            "SELECT set_config('app.current_tenant_id', $1, true)",
            tenant_a,
        )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.execution_trajectories "
            "WHERE trajectory_id=$1",
            trajectory_id,
        ) == 1


async def test_live_postgres_review_receipts_are_atomic_scoped_and_immutable() -> None:
    dsn = _disposable_dsn()
    # This test may only initialize a *new* disposable database.
    raw = await asyncpg.connect(dsn)
    tenant_a, tenant_b = (str(uuid.uuid4()) for _ in range(2))
    subject_a, other_user, reviewer_id = (str(uuid.uuid4()) for _ in range(3))
    try:
        await _prepare_disposable_database(raw)
        for tenant_id in (tenant_a, tenant_b):
            await raw.execute(
                "INSERT INTO public.tenants(id) VALUES ($1)",
                uuid.UUID(tenant_id),
            )
        for user_id, tenant_id in (
            (subject_a, tenant_a),
            (other_user, tenant_a),
            (reviewer_id, tenant_a),
        ):
            await raw.execute(
                "INSERT INTO public.auth_users(user_id, tenant_id) VALUES ($1,$2)",
                uuid.UUID(user_id), uuid.UUID(tenant_id),
            )
        store = PostgresOutcomeStore()
        governed = GovernedVerificationReviewEvidence(
            tenant_id=tenant_a, subject_user_id=subject_a, store=store,
        )
        original = _observation(1, tenant_a)
        before = deepcopy(original)
        result = await governed.record_review(
            original, reviewer=_principal(reviewer_id, tenant_a, reviewer=True),
        )
        assert result["stored"] is True
        assert result["receipt_count"] == 2
        assert original == before

        # Reinitialize a separate adapter, and read from two different
        # production PostgreSQL connection pools/transactions, not a cache.
        reconstructed = GovernedVerificationReviewEvidence(
            tenant_id=tenant_a, subject_user_id=subject_a,
            store=PostgresOutcomeStore(),
        )
        evidence = await reconstructed.require_persisted_reviews(
            [original], subject=_principal(subject_a, tenant_a),
        )
        assert evidence["persisted_decision_count"] == 1
        assert evidence["persisted_receipt_count"] == 2
        assert evidence["receipt_scope_verified"] is True
        assert evidence["policy_activated"] is False

        refs = ["pg:reward:1", "pg:needed:1"]
        same_scope = await asyncio.to_thread(
            store.list_scoped_outcomes_by_ids,
            tenant_a, user_id=subject_a,
            source="intelligence.ml", outcome_ids=refs,
        )
        assert len(same_scope) == 2
        assert all(row["user_id"] == subject_a for row in same_scope)
        assert "NEVER_PERSIST_REVIEW_PROMPT" not in str(same_scope)

        # Both SQL predicates apply. Neither the same-tenant other user nor
        # another tenant may see the caller's receipt by knowing its ID.
        for wrong_tenant, wrong_user in (
            (tenant_b, subject_a), (tenant_a, other_user),
        ):
            assert await asyncio.to_thread(
                store.list_scoped_outcomes_by_ids,
                wrong_tenant, user_id=wrong_user,
                source="intelligence.ml", outcome_ids=refs,
            ) == []
        assert await asyncio.to_thread(
            store.list_scoped_outcomes_by_ids,
            tenant_a, user_id=subject_a,
            source="runtime.execution", outcome_ids=refs,
        ) == []

        # KCOG-01B9: the API submission owner must independently load the
        # real persisted decision and feature snapshot from the canonical
        # runtime learning lineage. Reviewers do not submit policy matrices.
        lineage = PostgresTrajectoryStore()
        trajectory = ExecutionTrajectory(
            trajectory_id="pg-review-lineage-1",
            tenant_id=tenant_a,
            user_id=subject_a,
            request_id="pg-review-request-1",
            correlation_id="pg-review-correlation-1",
            session_id="pg-review-session-1",
            conversation_id="pg-review-conversation-1",
            policy_decision_id="pg-review-policy-1",
            executed_topology="direct",
            execution_status="success",
            completed_at=datetime.now(timezone.utc),
            actual_provider="ollama-local",
            actual_model="installed-ci-model",
            fallback_level=0,
            degraded_mode=False,
            response_source="model",
        )
        await lineage.save_async(trajectory)
        feature = FeatureSnapshot(
            feature_snapshot_id="pg-review-snapshot-1",
            trajectory_id=trajectory.trajectory_id,
            tenant_id=tenant_a,
            user_id=subject_a,
            request_id="pg-review-request-1",
            correlation_id="pg-review-correlation-1",
            feature_version="pg-verification-features-v1",
            created_at=datetime.now(timezone.utc),
            metadata={
                "snapshot_origin": "ci_decision_time",
                "policy_decision_id": trajectory.policy_decision_id,
            },
        )
        await lineage.save_feature_snapshot_async(feature)
        decision = DecisionObservation(
            decision_observation_id="pg-review-decision-1",
            trajectory_id=trajectory.trajectory_id,
            feature_snapshot_id=feature.feature_snapshot_id,
            decision_type="respond_strategy",
            behavior_policy_id="pg-verified-baseline",
            behavior_policy_version="v1",
            candidate_actions=tuple(_ACTIONS),
            eligible_actions=tuple(_ACTIONS),
            chosen_action=_ACTIONS[0],
            chosen_probability=0.5,
            action_probabilities={_ACTIONS[0]: 0.5, _ACTIONS[1]: 0.5},
            created_at=datetime.now(timezone.utc),
            ope_eligible=True,
            tenant_id=tenant_a,
            user_id=subject_a,
            metadata={
                "verification_policy_snapshot": {
                    "schema_version": "verification_policy_snapshot_v1",
                    "candidate_policy_id": "pg-frozen-candidate",
                    "candidate_policy_version": "v1",
                    "candidate_probabilities": {
                        _ACTIONS[0]: 0.25, _ACTIONS[1]: 0.75,
                    },
                    "risk_class": "low",
                    "utility_policy_version": "pg-independent-review-v1",
                },
            },
        )
        await lineage.save_decision_observation_async(decision)
        reviewer = _principal(reviewer_id, tenant_a, reviewer=True)
        authenticated_review = VerificationReviewWorkflow(
            lineage_store=PostgresTrajectoryStore(),
            outcome_store=PostgresOutcomeStore(),
        )
        reviewed = ReviewJudgement(
            decision_observation_id=decision.decision_observation_id,
            subject_user_id=subject_a,
            reward=0.9,
            verification_needed=True,
        )
        # B2C3A: a persisted policy choice alone is NOT sufficient to admit
        # reviewer reward. Verify that the *original* selected execution
        # outcome exists before storing independent labels.
        with pytest.raises(ValueError, match="Exactly one selected execution"):
            await authenticated_review.submit(
                reviewed, reviewer=reviewer,
                correlation_id="pg-review-correlation-1",
            )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE decision_observation_id='pg-review-decision-1'"
            " AND source='intelligence.ml'"
        ) == 0

        await store.save_outcome_async({
            "outcome_id": "pg-review-selected-execution-1",
            "trajectory_id": trajectory.trajectory_id,
            "decision_observation_id": decision.decision_observation_id,
            "tenant_id": tenant_a,
            "user_id": subject_a,
            "request_id": trajectory.request_id,
            "correlation_id": trajectory.correlation_id,
            "session_id": trajectory.session_id,
            "conversation_id": trajectory.conversation_id,
            "source": "runtime.execution",
            "status": "success",
            "response_completed": True,
            "persistence_success": True,
            "fallback_count": 0,
            "metadata": {
                "actual_provider": trajectory.actual_provider,
                "actual_model": trajectory.actual_model,
                "model_calls": 1,
                "tool_calls": 0,
                "transcript_persistence_status": "persisted",
                "selected_strategy_execution": {
                    "schema_version": "selected_strategy_execution_v1",
                    "policy_decision_id": trajectory.policy_decision_id,
                    "policy_version": decision.behavior_policy_version,
                    "selected_action": decision.chosen_action,
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
        submitted = await authenticated_review.submit(
            reviewed, reviewer=reviewer,
            correlation_id="pg-review-correlation-1",
        )
        assert submitted["stored"] is True
        assert submitted["decision_provenance"] == "durable_runtime_lineage"
        assert submitted["policy_activated"] is False
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE decision_observation_id='pg-review-decision-1'"
            " AND source='intelligence.ml'"
        ) == 2
        with pytest.raises(OutcomeStoreError):
            await authenticated_review.submit(
                reviewed, reviewer=reviewer,
            )
        with pytest.raises(LookupError):
            await authenticated_review.submit(
                reviewed,
                reviewer=_principal(reviewer_id, tenant_b, reviewer=True),
            )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE decision_observation_id='pg-review-decision-1'"
        ) == 3

        # KCOG-01C0: exercise the actual ChatRuntime selection recorder
        # against the same PostgreSQL lineage schema. This is not a
        # synthetic randomized candidate or a reviewed OPE-eligible decision.
        runtime = ChatRuntime.__new__(ChatRuntime)
        runtime._trajectory_recorder = TrajectoryRecorder(store=PostgresTrajectoryStore())
        runtime_trajectory = ExecutionTrajectory(
            trajectory_id="pg-runtime-selection-1",
            request_id="pg-runtime-request-1",
            correlation_id="pg-runtime-corr-1",
            tenant_id=tenant_a,
            user_id=subject_a,
        )
        policy_decision = ExecutionDecision(
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["verification"],
            policy_decision_id="pg-policy-authorized-1",
            policy_version="pg-v1",
        )
        topology_id = await runtime._record_learning_decision(
            runtime_trajectory, policy_decision,
        )
        assert topology_id
        saved = await asyncio.to_thread(
            PostgresTrajectoryStore().list_decision_observations,
            runtime_trajectory.trajectory_id,
            tenant_id=tenant_a,
        )
        assert len(saved) == 2
        planned = next(item for item in saved if item.decision_type == "respond_strategy")
        assert planned.chosen_action == "verify_then_respond"
        assert planned.feature_snapshot_id == saved[0].feature_snapshot_id
        assert planned.ope_eligible is False
        assert planned.chosen_probability is None
        assert planned.action_probabilities == {}
        assert planned.ope_ineligible_reason == "missing_propensity"
        assert "verification_policy_snapshot" not in planned.metadata

        # B2C3B: actual ChatRuntime-selected decision-time lineage is linked
        # through the original OutcomeRecorder/OutcomeStore write. This is a
        # test-only typed provider receipt, NOT a live model or proof of answer
        # accuracy. The real PostgreSQL readback must find the strategy ID.
        strategy_link = runtime_trajectory.metadata[
            "selected_strategy_decision_observation_v1"
        ]
        assert strategy_link["decision_observation_id"] == planned.decision_observation_id
        assert strategy_link["trajectory_id"] == runtime_trajectory.trajectory_id
        assert strategy_link["selected_action"] == "verify_then_respond"
        assert strategy_link["ope_eligible"] is False
        assert topology_id != planned.decision_observation_id

        runtime._outcome_recorder = OutcomeRecorder(store=PostgresOutcomeStore())
        test_meter = SimpleNamespace(
            model_calls=1, tool_calls=0, reasoning_steps=2,
        )
        proven_provider = {
            "response_source": "model",
            "actual_provider": "ollama",
            "actual_model": "installed-test-receipt-only",
            "runtime_engine": "ollama",
            "fallback_level": 0,
            "degraded_mode": False,
            "provenance": ResponseProvenance(
                response_source=ResponseSource.MODEL,
                provider="ollama",
                model="installed-test-receipt-only",
                engine="ollama",
                correlation_id=runtime_trajectory.correlation_id,
                decision_id=policy_decision.policy_decision_id,
            ),
            "reasoning_id": "test-only-verifier-execution",
            "reasoning_status": "abstained",
            "reasoning_activation": "core_defaults",
            "reasoning_generation_mode": "model_after_authorized_reasoning",
            "reasoning_model_calls": 0,
            "reasoning_model_attribution_status": "not_executed",
            "verification_strategy_executed": True,
            "reasoning_steps": 2,
            "reasoning_modes": ["verification"],
        }
        ctx_token = set_correlation_context(CorrelationContext(
            request_id=runtime_trajectory.request_id,
            correlation_id=runtime_trajectory.correlation_id,
            tenant_id=tenant_a,
            user_id=subject_a,
        ))
        try:
            await runtime._record_trajectory_completion(
                runtime_trajectory,
                policy_decision,
                "Test-only synthetic completed answer.",
                time.time() - 0.01,
                test_meter,
                proven_provider,
                {},
            )
            await runtime._record_execution_outcome(
                trajectory_id=runtime_trajectory.trajectory_id,
                decision=policy_decision,
                decision_observation_id=topology_id,
                text="Test-only synthetic completed answer.",
                start=time.time() - 0.01,
                meter=test_meter,
                memory_meta={},
                success=True,
                transcript_meta={"transcript_persistence_status": "persisted"},
                provider_meta=proven_provider,
                selected_strategy_decision=strategy_link,
            )
        finally:
            reset_correlation_context(ctx_token)

        actual_rows = await asyncio.to_thread(
            PostgresOutcomeStore().get_for_trajectory,
            runtime_trajectory.trajectory_id,
            tenant_id=tenant_a,
        )
        execution_rows = [
            item for item in actual_rows
            if item.get("source") == "runtime.execution"
            and item.get("decision_observation_id") == planned.decision_observation_id
        ]
        assert len(execution_rows) == 1
        assert execution_rows[0]["metadata"]["topology_decision_observation_id"] == topology_id
        assert execution_rows[0]["metadata"][
            "selected_strategy_execution"
        ]["status"] == "selected_runtime_path_observed"
        assert execution_rows[0]["metadata"][
            "selected_strategy_execution"
        ]["ope_eligible"] is False
        assert await asyncio.to_thread(
            PostgresTrajectoryStore().get,
            runtime_trajectory.trajectory_id,
            tenant_id=tenant_b,
        ) is None
        assert await asyncio.to_thread(
            PostgresOutcomeStore().get_for_trajectory,
            runtime_trajectory.trajectory_id,
            tenant_id=tenant_b,
        ) == []
        with pytest.raises(ValueError, match="not verification-OPE eligible"):
            await authenticated_review.submit(
                ReviewJudgement(
                    decision_observation_id=planned.decision_observation_id,
                    subject_user_id=subject_a,
                    reward=0.95,
                    verification_needed=True,
                ),
                reviewer=reviewer,
            )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE decision_observation_id=$1"
            " AND source='intelligence.ml'",
            planned.decision_observation_id,
        ) == 0

        # KCOG-01C1B2C2: an interrupted selected path uses the *same*
        # PostgresTrajectoryStore and tenant RLS as frozen runtime decisions.
        # It cannot create a successful assistant outcome or reviewer label.
        cancel_ctx = ChatExecutionContext(
            user_id=subject_a,
            tenant_id=tenant_a,
            session_id="pg-cancelled-session",
            conversation_id="pg-cancelled-conversation",
            request_id="pg-cancelled-request",
            correlation_id="pg-cancelled-correlation",
        )
        cancel_request = ChatExecutionRequest(
            messages=[{"role": "user", "content": "Do not persist partial output"}],
            context=cancel_ctx,
            preferred_provider="ollama",
            preferred_model="installed-model",
        )
        cancel_plan = AuthorizedExecutionPlan(
            execution_id="pg-cancelled-execution",
            policy_decision_id="pg-cancelled-policy",
            authorized_user_id=subject_a,
            authorized_tenant_id=tenant_a,
            authorized_session_id=cancel_ctx.session_id,
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["verification"],
            budget=ExecutionBudget(max_model_calls=2, max_reasoning_steps=4),
        )
        cancel_decision = ExecutionDecision(
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["verification"],
            policy_decision_id=cancel_plan.policy_decision_id,
            policy_version="pg-v1",
        )
        cancel_traj = ExecutionTrajectory(
            trajectory_id="pg-cancelled-trajectory",
            request_id=cancel_ctx.request_id,
            correlation_id=cancel_ctx.correlation_id,
            tenant_id=tenant_a,
            user_id=subject_a,
            session_id=cancel_ctx.session_id,
            conversation_id=cancel_ctx.conversation_id,
        )
        cancel_meter = ExecutionBudgetMeter(cancel_plan.budget)
        cancel_meter.start()
        await runtime._record_cancelled_trajectory(
            cancel_traj,
            cancel_decision,
            cancel_request,
            cancel_plan,
            cancel_meter,
            1.0,
        )
        persisted_cancel = await asyncio.to_thread(
            PostgresTrajectoryStore().get,
            cancel_traj.trajectory_id,
            tenant_id=tenant_a,
        )
        assert persisted_cancel is not None
        assert persisted_cancel.execution_status == "cancelled"
        assert persisted_cancel.error_code == "CHAT_REQUEST_CANCELLED"
        assert persisted_cancel.policy_decision_id == cancel_plan.policy_decision_id
        assert persisted_cancel.user_id == subject_a
        assert persisted_cancel.actual_provider is None
        assert persisted_cancel.actual_model is None
        assert persisted_cancel.response_source is None
        assert persisted_cancel.completed_at is not None
        assert await asyncio.to_thread(
            PostgresTrajectoryStore().get,
            cancel_traj.trajectory_id,
            tenant_id=tenant_b,
        ) is None
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE trajectory_id=$1",
            cancel_traj.trajectory_id,
        ) == 0
        await _assert_cancelled_trajectory_rls_is_real(
            raw,
            tenant_a=tenant_a,
            tenant_b=tenant_b,
            trajectory_id=cancel_traj.trajectory_id,
            subject_id=subject_a,
        )
        with pytest.raises(ValueError, match="not verification-OPE eligible"):
            await authenticated_review.submit(
                ReviewJudgement(
                    decision_observation_id=planned.decision_observation_id,
                    subject_user_id=subject_a,
                    reward=0.9,
                    verification_needed=True,
                ),
                reviewer=reviewer,
            )
        assert await raw.fetchval(
            """SELECT count(*) FROM public.outcome_records
               WHERE decision_observation_id=$1""",
            planned.decision_observation_id,
        ) == 0

        # KCOG-01C1B1: persist an actual independently checked *permission*
        # probe to PostgreSQL. The second strategy is policy-permitted, NOT
        # proven executable, randomized, OPE-eligible or reviewed.
        policy_owner = RuntimePolicyEnforcer()
        scoped_request = PolicyEvaluationRequest(
            user_id=subject_a,
            tenant_id=tenant_a,
            session_id="pg-permission-session-1",
            requested_reasoning_modes=[],
            max_model_calls=10,
        )
        selected_policy = await policy_owner.evaluate(scoped_request)
        permission = await policy_owner.probe_optional_verification(
            scoped_request,
            selected_policy,
            direct_plan_authorized=True,
        )
        assert permission.policy_permitted_actions == (
            "respond_direct", "verify_then_respond",
        )
        permission_traj = ExecutionTrajectory(
            trajectory_id="pg-policy-permission-selection-1",
            request_id="pg-policy-permission-request-1",
            correlation_id="pg-policy-permission-corr-1",
            tenant_id=tenant_a,
            user_id=subject_a,
        )
        direct_plan = ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id=selected_policy.decision_id,
            policy_version=selected_policy.policy_version,
            policy_constraints={
                "response_strategy_policy_probe": permission.to_metadata(),
            },
        )
        from ai_karen_engine.core.runtime.reasoning_bridge import (
            get_runtime_reasoning_bridge,
        )

        readiness = (
            get_runtime_reasoning_bridge().inspect_optional_verification_readiness(
                permission=permission,
                decision=direct_plan,
                preferred_provider=None,
                preferred_model=None,
            )
        )
        assert readiness.status == "unverified"
        assert "model_selection_not_runtime_resolved" in readiness.reason_codes
        direct_plan.policy_constraints["verification_alternative_readiness"] = (
            readiness.to_metadata()
        )
        assert await runtime._record_learning_decision(permission_traj, direct_plan)
        records = await asyncio.to_thread(
            PostgresTrajectoryStore().list_decision_observations,
            permission_traj.trajectory_id,
            tenant_id=tenant_a,
        )
        permission_strategy = next(
            item for item in records if item.decision_type == "respond_strategy"
        )
        frozen = await asyncio.to_thread(
            PostgresTrajectoryStore().get_feature_snapshot,
            permission_strategy.feature_snapshot_id,
            tenant_id=tenant_a,
        )
        assert frozen is not None
        assert frozen.metadata["response_strategy_policy_probe"] == (
            permission.to_metadata()
        )
        assert permission_strategy.metadata["response_strategy_policy_probe"] == (
            permission.to_metadata()
        )
        assert frozen.metadata["verification_alternative_readiness"] == (
            readiness.to_metadata()
        )
        assert permission_strategy.metadata["verification_alternative_readiness"] == (
            readiness.to_metadata()
        )
        assert permission_strategy.eligible_actions == ("respond_direct",)
        assert permission_strategy.chosen_probability is None
        assert permission_strategy.action_probabilities == {}
        assert permission_strategy.ope_eligible is False
        with pytest.raises(ValueError, match="not verification-OPE eligible"):
            await authenticated_review.submit(
                ReviewJudgement(
                    decision_observation_id=permission_strategy.decision_observation_id,
                    subject_user_id=subject_a,
                    reward=0.9,
                    verification_needed=True,
                ),
                reviewer=reviewer,
            )
        assert await raw.fetchval(
            """SELECT count(*) FROM public.outcome_records
               WHERE decision_observation_id=$1""",
            permission_strategy.decision_observation_id,
        ) == 0

        # KCOG-01C1B2B1: persist a real, scoped *unverified* execution
        # observation through the existing runtime OutcomeRecorder. Neither
        # an empty model receipt nor a saved diagnostic is a verification
        # judgment, and the selected-only row remains reviewer-ineligible.
        import time
        from types import SimpleNamespace

        from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
        from ai_karen_engine.platform.observability.context import (
            CorrelationContext,
            reset_correlation_context,
            set_correlation_context,
        )

        runtime._outcome_recorder = OutcomeRecorder(
            store=PostgresOutcomeStore(),
        )
        observation_context = set_correlation_context(CorrelationContext(
            correlation_id=permission_traj.correlation_id,
            request_id=permission_traj.request_id,
            tenant_id=tenant_a,
            user_id=subject_a,
        ))
        try:
            await runtime._record_execution_outcome(
                trajectory_id=permission_traj.trajectory_id,
                decision=direct_plan,
                decision_observation_id=permission_strategy.decision_observation_id,
                text="",
                start=time.time(),
                meter=SimpleNamespace(
                    model_calls=0, tool_calls=0, reasoning_steps=0,
                ),
                memory_meta={},
                success=False,
                transcript_meta={"transcript_persistence_status": "skipped"},
                provider_meta={},
            )
        finally:
            reset_correlation_context(observation_context)
        assert await raw.fetchval(
            """SELECT payload->'metadata'->'selected_strategy_execution'
                      ->>'status'
               FROM public.outcome_records
               WHERE source='runtime.execution'
                 AND decision_observation_id=$1""",
            permission_strategy.decision_observation_id,
        ) == "unverified"
        assert await raw.fetchval(
            """SELECT payload->'metadata'->'selected_strategy_execution'
                      ->>'ope_eligible'
               FROM public.outcome_records
               WHERE source='runtime.execution'
                 AND decision_observation_id=$1""",
            permission_strategy.decision_observation_id,
        ) == "false"
        with pytest.raises(ValueError, match="not verification-OPE eligible"):
            await authenticated_review.submit(
                ReviewJudgement(
                    decision_observation_id=permission_strategy.decision_observation_id,
                    subject_user_id=subject_a,
                    reward=1.0,
                    verification_needed=True,
                ),
                reviewer=reviewer,
            )

        # A second attempted decision with an original *label* ID causes
        # statement two to conflict. Statement one MUST roll back as well.
        conflict = _observation(2, tenant_a)
        conflict.metadata["verification_label_ref"] = "pg:needed:1"
        with pytest.raises(OutcomeStoreError):
            await governed.record_review(
                conflict,
                reviewer=_principal(reviewer_id, tenant_a, reviewer=True),
            )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE outcome_id='pg:reward:2'"
        ) == 0
        assert await raw.fetchval(
            "SELECT count(*) FROM public.outcome_records "
            "WHERE outcome_id='pg:needed:1'"
        ) == 1

        # Tampering with a committed payload is detectable even when the
        # database user holding the direct test connection is a superuser.
        await raw.execute(
            """
            UPDATE public.outcome_records
            SET payload=jsonb_set(payload, '{metadata,value}', '0.10'::jsonb)
            WHERE outcome_id='pg:reward:1'
            """
        )
        with pytest.raises(OutcomeStoreError, match="does not match"):
            await reconstructed.require_persisted_reviews(
                [original], subject=_principal(subject_a, tenant_a),
            )
        await _assert_rls_is_real(
            raw, tenant_a=tenant_a, tenant_b=tenant_b,
            receipt_id="pg:needed:1", subject_id=subject_a,
        )
    finally:
        await raw.close()
