"""KCM-02B3C2A: actual scoped reviewer admission against isolated PostgreSQL.

No mock transactions, fake persistence, hidden database fallback or shared
production database. Run only with the explicit disposable dedicated DB.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.intelligence.ml.contracts import (
    MLModelManifest, ModelStatus, Prediction, PredictionTask,
)
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkConfig
from ai_karen_engine.core.intelligence.ml.evaluation.corpus import (
    CanonicalEvaluationCorpus,
)
from ai_karen_engine.core.intelligence.ml.evaluation.evidence import (
    EvaluationEvidenceStore,
)
from ai_karen_engine.core.intelligence.ml.evaluation.reviewed_oracle_evidence import (
    GovernedCuratedOracleReviewEvidence,
)
from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
from ai_karen_engine.core.intelligence.ml.online_learning import MLOutcomeRecord
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStoreError, PostgresOutcomeStore,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = (
    "20261003010000_20_runtime_outcome_evidence.sql",
    "20261019020000_37_intelligence_ml_outcome_evidence.sql",
)


def _disposable_database() -> str:
    raw = os.environ.get("KAREN_TEST_ORACLE_DATABASE_URL", "")
    parsed = urlparse(raw)
    if not raw:
        pytest.skip("Dedicated disposable KCM reviewer PostgreSQL DB not configured")
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.path != "/karen_kcm_oracle_test"
        or parsed.username != "postgres"
        or os.environ.get("DATABASE_URL") != raw
    ):
        pytest.fail("Refuse KCM reviewer proof outside exact disposable PostgreSQL DB")
    return raw


async def _prepare(raw: asyncpg.Connection) -> None:
    assert await raw.fetchval("SELECT current_database()") == "karen_kcm_oracle_test"
    await raw.execute(
        """
        CREATE TABLE public.tenants (id uuid PRIMARY KEY);
        CREATE TABLE public.auth_users (
            user_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES public.tenants(id)
        );
        """
    )
    for file in _MIGRATIONS:
        await raw.execute(
            (_ROOT / "supabase" / "migrations" / file).read_text(encoding="utf-8")
        )
    enforced = await raw.fetchrow(
        """
        SELECT relrowsecurity, relforcerowsecurity
        FROM pg_class WHERE oid = 'public.outcome_records'::regclass
        """
    )
    assert enforced is not None
    assert enforced["relrowsecurity"] and enforced["relforcerowsecurity"]
    assert await raw.fetchval(
        """SELECT COUNT(*) FROM pg_policies
           WHERE schemaname='public' AND tablename='outcome_records'
             AND policyname='outcome_records_tenant_scope'"""
    ) == 1
    await raw.execute(
        """
        CREATE ROLE karen_kcm_oracle_ci_reader NOLOGIN;
        GRANT USAGE ON SCHEMA public TO karen_kcm_oracle_ci_reader;
        GRANT SELECT, INSERT ON public.outcome_records
            TO karen_kcm_oracle_ci_reader;
        """
    )


async def _canonical_evidence(
    root: Path, *, tenant_id: str, subject_user_id: str,
    store: PostgresOutcomeStore,
) -> tuple[MLModelManifest, str]:
    """Execute the actual canonical runner and append exact numeric case evidence."""
    model_artifact = root / "candidate-model.bin"
    model_artifact.write_bytes(b"exact-oracle-test-artifact")
    task = PredictionTask.INTENT
    model_id = (
        "tenant-" + hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
        + "-curated-oracle-proof"
    )
    manifest = MLModelManifest(
        model_id=model_id,
        purpose=task.value,
        architecture="trained",
        artifact_path=str(model_artifact),
        artifact_hash=hashlib.sha256(model_artifact.read_bytes()).hexdigest(),
        model_version="v3",
        feature_version="features-2",
        status=ModelStatus.CANDIDATE.value,
    )
    registry = MLModelRegistry(registry_dir=str(root))
    registry.register(manifest)
    canonical_case = CanonicalEvaluationCorpus.get_cases(task=task)[0]

    class ExactCandidatePredictor:
        def predict(self, features):
            assert features.text == canonical_case.input_text
            return Prediction(
                task=task, label=canonical_case.expected_label,
                model_id=manifest.model_id,
                model_version=manifest.model_version,
                feature_version=manifest.feature_version,
                probability=0.95,
                confidence=0.95,
                fallback_used=False,
            )

    benchmark = await BenchmarkRunner().run(
        ExactCandidatePredictor(),
        BenchmarkConfig(
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            task=task,
            dataset_version=CanonicalEvaluationCorpus.DATASET_VERSION,
            case_ids=[canonical_case.case_id],
        ),
    )
    assert benchmark.sample_count == 1
    assert benchmark.outcomes[0].correct is True
    receipt = EvaluationEvidenceStore(root)._record(manifest, benchmark)
    verdict = benchmark.outcomes[0]
    case_hash = hashlib.sha256(verdict.case_id.encode("utf-8")).hexdigest()[:24]
    numeric_record = MLOutcomeRecord(
        outcome_id="kcm_pg_numeric_" + receipt,
        task=task, model_id=manifest.model_id,
        model_version=manifest.model_version,
        feature_version=manifest.feature_version,
        predicted_label="", expected_label="",
        correct=verdict.correct, raw_probability=0.95,
        calibrated_probability=0.95, confidence=0.95,
        latency_ms=verdict.latency_ms, fallback_used=False,
        calibration_error=0.05,
    )
    result = await GovernedMLLearningEvidence(
        tenant_id=tenant_id, user_id=subject_user_id, store=store,
    ).record_verified_batch([
        (numeric_record, "heldout_evaluation", f"benchmark:{receipt}:{case_hash}")
    ])
    assert result["stored"] is True
    assert result["stored_count"] == 1
    return manifest, receipt


@pytest.mark.asyncio
async def test_real_postgres_exact_oracle_reviewer_receipt_rls_and_replay(tmp_path):
    dsn = _disposable_database()
    raw = await asyncpg.connect(dsn)
    tenant_a, tenant_b = (str(uuid.uuid4()) for _ in range(2))
    subject_a, reviewer_a, subject_b = (str(uuid.uuid4()) for _ in range(3))
    try:
        await _prepare(raw)
        for tenant in (tenant_a, tenant_b):
            await raw.execute(
                "INSERT INTO public.tenants(id) VALUES ($1)", uuid.UUID(tenant)
            )
        for user, tenant in (
            (subject_a, tenant_a), (reviewer_a, tenant_a), (subject_b, tenant_b)
        ):
            await raw.execute(
                "INSERT INTO public.auth_users(user_id, tenant_id) VALUES ($1,$2)",
                uuid.UUID(user), uuid.UUID(tenant),
            )
        store = PostgresOutcomeStore()
        manifest, receipt = await _canonical_evidence(
            tmp_path, tenant_id=tenant_a, subject_user_id=subject_a, store=store,
        )
        subject = AuthenticatedPrincipal(user_id=subject_a, tenant_id=tenant_a)
        reviewer = AuthenticatedPrincipal(
            user_id=reviewer_a, tenant_id=tenant_a,
            session_id="separately-authenticated-reviewer",
            permissions=[Permission.BENCHMARK_ORACLE_REVIEW.value],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        adapter = GovernedCuratedOracleReviewEvidence(
            tenant_id=tenant_a, subject_user_id=subject_a,
            registry_dir=tmp_path, store=store, maximum_cases=1,
        )
        recorded = await adapter.record_review(
            subject=subject, reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
        assert recorded.exact_cohort_reviewer_acknowledged is True
        assert recorded.independent_ground_truth_verified is False
        assert recorded.training_authorized is False
        assert recorded.execution_authorized is False
        assert await adapter.inspect_review(
            subject=subject, model_id=manifest.model_id, receipt_id=receipt,
        ) == recorded

        numeric = await asyncio.to_thread(
            store.list_scoped_ml_predictor_outcomes,
            tenant_a, user_id=subject_a, limit=1,
        )
        assert len(numeric) == 1
        assert numeric[0]["metadata"]["schema_version"] == "ml_predictor_evidence_v1"
        assert await raw.fetchval(
            """SELECT count(*) FROM public.outcome_records
               WHERE tenant_id=$1 AND user_id=$2 AND source='intelligence.ml'""",
            uuid.UUID(tenant_a), uuid.UUID(subject_a),
        ) == 3
        reviewer_row = await raw.fetchrow(
            """SELECT outcome_id, payload FROM public.outcome_records
               WHERE tenant_id=$1 AND user_id=$2
               AND payload->'metadata'->>'schema_version'
                   = 'kcm_curated_oracle_reviewer_observation_v1'
               AND payload->'metadata'->>'review_phase' = 'confirmed'""",
            uuid.UUID(tenant_a), uuid.UUID(subject_a),
        )
        assert reviewer_row is not None
        review_id = reviewer_row["outcome_id"]
        assert (
            CanonicalEvaluationCorpus.get_cases(
                task=PredictionTask.INTENT,
            )[0].input_text not in str(reviewer_row["payload"])
        )

        with pytest.raises(OutcomeStoreError):
            await adapter.record_review(
                subject=subject, reviewer=reviewer,
                model_id=manifest.model_id, receipt_id=receipt,
            )
        assert await asyncio.to_thread(
            store.list_scoped_outcomes_by_ids,
            tenant_b, user_id=subject_b, source="intelligence.ml",
            outcome_ids=[review_id],
        ) == []
        with pytest.raises(PermissionError):
            await adapter.inspect_review(
                subject=AuthenticatedPrincipal(
                    tenant_id=tenant_b, user_id=subject_b,
                ),
                model_id=manifest.model_id, receipt_id=receipt,
            )

        # Prove actual tenant FORCE RLS using a non-superuser principal.
        async with raw.transaction():
            await raw.execute("SET LOCAL ROLE karen_kcm_oracle_ci_reader")
            await raw.execute(
                "SELECT set_config('app.current_tenant_id',$1,true)", tenant_b
            )
            assert await raw.fetchval(
                "SELECT COUNT(*) FROM public.outcome_records WHERE outcome_id=$1",
                review_id,
            ) == 0
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with raw.transaction():
                    await raw.execute(
                        """
                        INSERT INTO public.outcome_records
                          (outcome_id,tenant_id,user_id,source,payload)
                        VALUES ($1,$2,$3,'intelligence.ml','{}'::jsonb)
                        """,
                        "kcm-oracle-forbidden", uuid.UUID(tenant_a),
                        uuid.UUID(subject_a),
                    )
            await raw.execute(
                "SELECT set_config('app.current_tenant_id',$1,true)", tenant_a
            )
            assert await raw.fetchval(
                "SELECT COUNT(*) FROM public.outcome_records WHERE outcome_id=$1",
                review_id,
            ) == 1

        # Altered exact-snapshot digest fails consumption despite the real row.
        await raw.execute(
            """
            UPDATE public.outcome_records
            SET payload=jsonb_set(
                payload,'{metadata,exact_snapshot_sha256}',to_jsonb($2::text)
            ) WHERE outcome_id=$1
            """,
            review_id, "0" * 64,
        )
        assert await adapter.inspect_review(
            subject=subject, model_id=manifest.model_id, receipt_id=receipt,
        ) is None
        assert len(await asyncio.to_thread(
            store.list_scoped_ml_predictor_outcomes,
            tenant_a, user_id=subject_a, limit=1,
        )) == 1
        # The issuer's separate, append-only withdrawal must immediately
        # invalidate the previously confirmed reviewer claim without
        # deleting the numeric benchmark evidence or touching another tenant.
        await raw.execute(
            """
            UPDATE public.outcome_records
            SET payload=jsonb_set(
                payload,'{metadata,exact_snapshot_sha256}',to_jsonb($2::text)
            ) WHERE outcome_id=$1
            """,
            review_id, adapter._snapshot(
                model_id=manifest.model_id, receipt_id=receipt,
            ).snapshot_sha256,
        )
        assert await adapter.inspect_review(
            subject=subject, model_id=manifest.model_id, receipt_id=receipt,
        ) is not None
        withdrawal_id = await adapter.withdraw_review(
            subject=subject, reviewer=reviewer,
            model_id=manifest.model_id, receipt_id=receipt,
        )
        assert withdrawal_id.startswith("kcm_curated_withdrawal_")
        assert await adapter.inspect_review(
            subject=subject, model_id=manifest.model_id, receipt_id=receipt,
        ) is None
        assert await raw.fetchval(
            "SELECT COUNT(*) FROM public.outcome_records "
            "WHERE tenant_id=$1 AND user_id=$2 AND source='intelligence.ml'",
            uuid.UUID(tenant_a), uuid.UUID(subject_a),
        ) == 4
        with pytest.raises(OutcomeStoreError):
            await adapter.withdraw_review(
                subject=subject, reviewer=reviewer,
                model_id=manifest.model_id, receipt_id=receipt,
            )
        assert await asyncio.to_thread(
            store.list_scoped_outcomes_by_ids,
            tenant_b, user_id=subject_b, source="intelligence.ml",
            outcome_ids=[withdrawal_id],
        ) == []
    finally:
        await raw.close()

