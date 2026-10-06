from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_runtime_composes_canonical_durable_trajectory_store() -> None:
    composition = _text("src/ai_karen_engine/core/runtime/composition.py")
    runtime = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert "trajectory_store: TrajectoryStore | None = None" in composition
    assert "get_trajectory_store" in composition
    assert "trajectory_store=get_trajectory_store()" in composition
    assert "store=self._composition.trajectory_store" in runtime
    assert "TrajectoryRecorder()" not in runtime


def test_live_chat_records_decision_time_lineage_before_execution() -> None:
    runtime = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert "await self._record_learning_decision(" in runtime
    assert "TOPOLOGY_FEATURES_V1" in runtime
    assert "DecisionType.EXECUTION_TOPOLOGY.value" in runtime
    assert "OpeEligibilityReason.MISSING_PROPENSITY.value" in runtime
    assert "chosen_probability=None" in runtime
    assert "action_probabilities={}" in runtime
    assert "decision_observation_id=decision_observation_id" in runtime


def test_learning_lineage_store_uses_tenant_transactions_not_legacy_db_helper() -> None:
    store = _text("src/ai_karen_engine/core/runtime/trajectory/store.py")

    assert "transaction_scope" in store
    assert "async_transaction_scope" in store
    assert "TrajectoryStoreError" in store
    assert "get_database_connection" not in store
    assert "except Exception:\n            pass" not in store


def test_learning_lineage_schema_is_migration_owned_and_rls_protected() -> None:
    migration = _text(
        "supabase/migrations/20261006010000_24_learning_decision_lineage.sql"
    )

    for table in (
        "execution_trajectories",
        "feature_snapshots",
        "decision_observations",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in migration
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in migration
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in migration

    assert "REFERENCES public.execution_trajectories" in migration
    assert "REFERENCES public.feature_snapshots" in migration


def test_learning_lineage_is_covered_by_privacy_export_and_erasure() -> None:
    privacy = _text("src/ai_karen_engine/services/privacy_compliance.py")

    for table in (
        "execution_trajectories",
        "feature_snapshots",
        "decision_observations",
        "outcome_records",
    ):
        assert privacy.count(f'"{table}"') >= 2


def test_dataset_builder_reads_all_lineage_under_explicit_tenant_scope() -> None:
    builder = _text(
        "src/ai_karen_engine/core/runtime/trajectory/dataset_builder.py"
    )

    assert "tenant_id=query.tenant_scope" in builder
    assert "get_for_trajectory(" in builder


def test_proactive_continuity_is_first_class_learning_lineage() -> None:
    learning = _text("src/ai_karen_engine/core/contracts/learning.py")
    runtime_contracts = _text(
        "src/ai_karen_engine/core/runtime/trajectory/learning_contracts.py"
    )
    ope_contracts = _text(
        "src/ai_karen_engine/core/intelligence/ml/policy_evaluation/contracts.py"
    )
    runtime = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert 'PROACTIVE_CONTINUITY = "proactive_continuity"' in learning
    assert 'PROACTIVE_CONTINUITY = "proactive_continuity"' in runtime_contracts
    assert 'PROACTIVE_CONTINUITY = "proactive_continuity"' in ope_contracts
    assert '"continuity_decision_observation_id"' in runtime
