"""Durable predictor evidence reuses Karen's one scoped OutcomeStore.

Offline InMemoryOutcomeStore is a test double only. This tests the same
strict-write and scoped-read contract, not a live PostgreSQL migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.durable_outcomes import (
    GovernedMLLearningEvidence,
)
from ai_karen_engine.core.intelligence.ml.online_learning import MLOutcomeRecord
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore, OutcomeStoreError, PostgresOutcomeStore,
)


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def observation(*, outcome_id="observed-1", correct=True, model="candidate"):
    return MLOutcomeRecord(
        outcome_id=outcome_id, task=PredictionTask.INTENT,
        model_id=model, model_version="v1", feature_version="v1",
        predicted_label="PRIVATE_USER_DATA_MUST_NOT_PERSIST",
        expected_label="PRIVATE_GROUND_TRUTH_MUST_NOT_PERSIST",
        correct=correct, raw_probability=0.9,
        calibrated_probability=0.9, confidence=0.9,
        latency_ms=15.0, fallback_used=False,
        calibration_error=0.01,
        metadata={"secret": "MUST_NOT_PERSIST"},
    )


@pytest.mark.asyncio
async def test_scoped_predictor_outcomes_survive_adapter_recreation_with_same_store():
    store = InMemoryOutcomeStore()
    first = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    receipt = await first.record_verified(
        observation(),
        label_source="heldout_evaluation",
        label_evidence_ref="heldout-dataset-v3-row-19",
    )
    assert receipt == {
        "outcome_id": "observed-1",
        "source": "intelligence.ml",
        "stored": True,
        "evidence_version": "ml_predictor_evidence_v1",
    }
    second = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    records = await second.load_verified()
    assert len(records) == 1
    assert records[0].model_id == "candidate"
    assert records[0].correct is True
    assert records[0].predicted_label == ""
    assert records[0].expected_label == ""
    assert float(records[0].timestamp) > 1_000_000
    stored_payload = store.list_for_tenant(TENANT, user_id=USER)[0]
    assert "PRIVATE_USER_DATA" not in str(stored_payload)
    assert "PRIVATE_GROUND_TRUTH" not in str(stored_payload)
    assert "MUST_NOT_PERSIST" not in str(stored_payload)


@pytest.mark.asyncio
async def test_dupe_label_evidence_cannot_fabricate_second_record():
    store = InMemoryOutcomeStore()
    service = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    await service.record_verified(
        observation(), label_source="human_review",
        label_evidence_ref="audit-ref-1",
    )
    with pytest.raises(OutcomeStoreError):
        await service.record_verified(
            observation(), label_source="human_review",
            label_evidence_ref="audit-ref-1",
        )
    assert len(await service.load_verified()) == 1


@pytest.mark.asyncio
async def test_unreviewed_or_model_self_assessed_labels_are_not_persisted():
    store = InMemoryOutcomeStore()
    service = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    with pytest.raises(ValueError, match="governed"):
        await service.record_verified(
            observation(), label_source="model_self_assessment",
            label_evidence_ref="self-1",
        )
    with pytest.raises(ValueError, match="reference"):
        await service.record_verified(
            observation(), label_source="heldout_evaluation",
            label_evidence_ref="",
        )
    assert await service.load_verified() == []


@pytest.mark.asyncio
async def test_scoped_reader_never_uses_other_user_or_tenant_training_data():
    store = InMemoryOutcomeStore()
    first = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    other = GovernedMLLearningEvidence(
        tenant_id=TENANT,
        user_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        store=store,
    )
    await first.record_verified(
        observation(), label_source="heldout_evaluation",
        label_evidence_ref="dataset-v3",
    )
    assert await other.load_verified() == []
    another_tenant = GovernedMLLearningEvidence(
        tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        user_id=USER, store=store,
    )
    assert await another_tenant.load_verified() == []


@pytest.mark.asyncio
async def test_new_adapter_rebuilds_profiles_from_store_without_process_cache():
    store = InMemoryOutcomeStore()
    service = GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    )
    for i in range(25):
        await service.record_verified(
            observation(
                outcome_id=f"active-{i}",
                correct=(i % 3 != 0),
                model="active",
            ),
            label_source="heldout_evaluation",
            label_evidence_ref=f"dataset-active-{i}",
        )
        await service.record_verified(
            observation(
                outcome_id=f"candidate-{i}",
                correct=True, model="candidate",
            ),
            label_source="heldout_evaluation",
            label_evidence_ref=f"dataset-candidate-{i}",
        )
    rebuilt = await GovernedMLLearningEvidence(
        tenant_id=TENANT, user_id=USER, store=store,
    ).build_adaptive_layer()
    active = rebuilt.get_profile("active", "v1", PredictionTask.INTENT)
    candidate = rebuilt.get_profile("candidate", "v1", PredictionTask.INTENT)
    assert active is not None and active.sample_count == 25
    assert candidate is not None and candidate.sample_count == 25
    assert candidate.accuracy > active.accuracy
    # The ML registry still owns actual promotion. Only an advisory
    # eligibility determination is returned by the online learning layer.
    eligible, reason = rebuilt.should_promote_candidate(
        "candidate", "v1", PredictionTask.INTENT, "active", "v1",
    )
    assert isinstance(eligible, bool)
    assert isinstance(reason, str)


def test_postgres_outcome_store_only_accepts_governed_ml_schema():
    payload = {
        "outcome_id": "ml-outcome-1",
        "source": "intelligence.ml",
        "tenant_id": TENANT, "user_id": USER,
        "metadata": {
            "schema_version": "ml_predictor_evidence_v1",
            "label_source": "heldout_evaluation",
            "label_evidence_ref": "heldout-data-v1-row",
            "task": PredictionTask.INTENT.value,
            "model_id": "intent-classifier",
            "model_version": "v1",
            "feature_version": "v1",
            "correct": True,
            "raw_probability": 0.9,
            "calibrated_probability": 0.9,
            "confidence": 0.9,
            "calibration_error": 0.01,
            "latency_ms": 10.0,
            "fallback_used": False,
        },
    }
    assert PostgresOutcomeStore._validated_identity(payload) == (
        TENANT, "intelligence.ml",
    )
    bad = {**payload, "metadata": {
        **payload["metadata"],
        "raw_training_data": "secret must be rejected",
    }}
    with pytest.raises(OutcomeStoreError, match="raw labels"):
        PostgresOutcomeStore._validated_identity(bad)


def test_existing_runtime_outcome_schema_and_tenant_rls_retained():
    sql = Path(
        "supabase/migrations/"
        "20261019020000_37_intelligence_ml_outcome_evidence.sql"
    ).read_text()
    assert "ALTER TABLE public.outcome_records" in sql
    assert "outcome_records_source_check" in sql
    assert "'runtime.execution', 'user.feedback', 'intelligence.ml'" in sql
    assert "CREATE TABLE" not in sql


@pytest.mark.asyncio
async def test_atomic_evaluation_batch_commits_complete_set_and_rejects_duplicates():
    store = InMemoryOutcomeStore()
    service = GovernedMLLearningEvidence(tenant_id=TENANT, user_id=USER, store=store)
    cases = [
        (observation(outcome_id="case-one"), "heldout_evaluation", "case-1"),
        (observation(outcome_id="case-two"), "heldout_evaluation", "case-2"),
    ]
    acknowledgement = await service.record_verified_batch(cases)
    assert acknowledgement["stored"] is True
    assert acknowledgement["stored_count"] == 2
    assert len(await service.load_verified()) == 2
    with pytest.raises(OutcomeStoreError):
        await service.record_verified_batch([
            (observation(outcome_id="case-three"), "heldout_evaluation", "case-3"),
            (observation(outcome_id="case-two"), "heldout_evaluation", "case-2"),
        ])
    assert len(await service.load_verified()) == 2
    assert not any(
        row["outcome_id"] == "case-three"
        for row in store.list_for_tenant(TENANT, user_id=USER)
    )


@pytest.mark.asyncio
async def test_atomic_batch_rejects_unsupported_store_instead_of_sequential_fallback():
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStore

    class SingleOnlyStore(InMemoryOutcomeStore):
        async def save_unique_outcomes_async(self, payloads):
            return await OutcomeStore.save_unique_outcomes_async(self, payloads)

    store = SingleOnlyStore()
    service = GovernedMLLearningEvidence(tenant_id=TENANT, user_id=USER, store=store)
    with pytest.raises(OutcomeStoreError, match="Atomic"):
        await service.record_verified_batch([
            (observation(outcome_id="first"), "heldout_evaluation", "case-1"),
            (observation(outcome_id="second"), "heldout_evaluation", "case-2"),
        ])
    assert await service.load_verified() == []


@pytest.mark.asyncio
async def test_postgres_batch_uses_one_transaction_and_rolls_back_on_second_failure(
    monkeypatch,
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from ai_karen_engine.core.runtime.outcome import store as store_module

    calls = []
    rolled_back = []
    staged = []

    class TransactionSession:
        async def execute(self, sql, params):
            calls.append(params["outcome_id"])
            if len(calls) == 2:
                return SimpleNamespace(rowcount=0)
            staged.append(dict(params))
            return SimpleNamespace(rowcount=1)

    @asynccontextmanager
    async def atomic_scope(tenant):
        assert tenant == TENANT
        try:
            yield TransactionSession()
        except Exception:
            staged.clear()
            rolled_back.append(True)
            raise

    monkeypatch.setattr(store_module, "async_transaction_scope", atomic_scope)
    store = PostgresOutcomeStore()
    service = GovernedMLLearningEvidence(tenant_id=TENANT, user_id=USER, store=store)
    with pytest.raises(OutcomeStoreError, match="not appended"):
        await service.record_verified_batch([
            (observation(outcome_id="tx-one"), "heldout_evaluation", "case-1"),
            (observation(outcome_id="tx-two"), "heldout_evaluation", "case-2"),
        ])
    assert calls == ["tx-one", "tx-two"]
    assert rolled_back == [True]
    assert staged == []
