from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_explicit_semantic_classifier_is_shared_by_primary_and_degraded_extractors() -> None:
    primary = _text(
        "src/ai_karen_engine/core/memory/signals/memory_signal_extractor.py"
    )
    degraded = _text(
        "src/ai_karen_engine/core/memory/signals/signal_rules.py"
    )

    assert "classify_explicit_user_memory(text)" in primary
    assert "classify_explicit_user_memory(text)" in degraded


def test_chat_memory_path_still_uses_governed_formation_not_writeback_queue() -> None:
    chat = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")
    manager = _text(
        "src/ai_karen_engine/core/memory/memory_runtime_manager.py"
    )

    assert "mem.process_interaction(" in chat
    assert "MemoryFormationService" in manager
    assert "MemoryWritebackSystem" not in chat
    assert "MemoryWritebackSystem" not in manager


def test_user_state_retrieval_is_a_neuro_recall_candidate_source() -> None:
    manager = _text(
        "src/ai_karen_engine/core/memory/memory_runtime_manager.py"
    )

    assert "PostgresUserStateRecallRetriever" in manager
    assert "NeuroRecall(" in manager
    assert "PostgresUserStateRecallRetriever()," in manager


def test_semantic_projection_remains_downstream_of_neurovault() -> None:
    manager = _text(
        "src/ai_karen_engine/core/memory/memory_runtime_manager.py"
    )
    projector = _text(
        "src/ai_karen_engine/platform/memory/postgres/derived_projector.py"
    )

    assert "PostgresNeuroVault" in manager
    assert "PostgresDerivedMemoryProjector" in manager
    assert 'signal.signal_type in {"identity_fact", "preference"}' in projector
    assert 'signal.signal_type == "goal"' in projector
    assert 'signal.signal_type == "prospective_event"' in projector


def test_new_user_state_tables_are_privacy_export_and_erasure_covered() -> None:
    privacy = _text("src/ai_karen_engine/services/privacy_compliance.py")

    assert '"memory_user_goal"' in privacy
    assert '"memory_prospective_item"' in privacy
    assert privacy.count('"memory_user_goal"') >= 2
    assert privacy.count('"memory_prospective_item"') >= 2


def test_formation_and_vault_share_one_sensitivity_metadata_contract() -> None:
    evaluator = _text(
        "src/ai_karen_engine/core/memory/formation/evaluator.py"
    )
    vault = _text(
        "src/ai_karen_engine/platform/memory/postgres/vault.py"
    )

    assert '"sensitivity_class"' in evaluator
    assert 'custom.get("sensitivity_class")' in vault
    assert '"memory_sensitivity"' not in evaluator


def test_derived_recall_requires_valid_canonical_source_event() -> None:
    vault = _text(
        "src/ai_karen_engine/platform/memory/postgres/vault.py"
    )
    profile = _text(
        "src/ai_karen_engine/platform/memory/postgres/profile_retriever.py"
    )
    user_state = _text(
        "src/ai_karen_engine/platform/memory/postgres/user_state_retriever.py"
    )
    procedural = _text(
        "src/ai_karen_engine/platform/memory/postgres/procedural_retriever.py"
    )

    assert "source_event.valid_to =" in vault
    for adapter in (profile, user_state, procedural):
        assert "MemoryEvent.consent_state == \"granted\"" in adapter
        assert "MemoryEvent.valid_to.is_(None)" in adapter


def test_semantic_user_model_schema_is_migration_owned_and_rls_protected() -> None:
    migration = _text(
        "supabase/migrations/20261005010000_21_memory_semantic_user_model.sql"
    )

    assert "CREATE TABLE IF NOT EXISTS public.memory_user_goal" in migration
    assert "CREATE TABLE IF NOT EXISTS public.memory_prospective_item" in migration
    assert "REFERENCES public.memory_event(event_id) ON DELETE CASCADE" in migration
    assert "ALTER TABLE public.memory_user_goal ENABLE ROW LEVEL SECURITY" in migration
    assert "ALTER TABLE public.memory_prospective_item ENABLE ROW LEVEL SECURITY" in migration
