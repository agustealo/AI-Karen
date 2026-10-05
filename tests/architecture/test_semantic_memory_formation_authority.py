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
    assert '"memory_open_loop"' in privacy
    assert privacy.count('"memory_user_goal"') >= 2
    assert privacy.count('"memory_prospective_item"') >= 2
    assert privacy.count('"memory_open_loop"') >= 2


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


def test_legacy_ram_goal_and_prospective_authorities_are_retired() -> None:
    goals_init = _text("src/ai_karen_engine/core/personalization/goals/__init__.py")
    memory_init = _text("src/ai_karen_engine/core/memory/__init__.py")

    for legacy_name in (
        "GoalLifecycle",
        "GoalStore",
        "IntentionLifecycle",
        "CommitmentLifecycle",
        "ProspectiveMemoryManager",
    ):
        assert legacy_name not in goals_init

    assert "ProspectiveMemoryStore" not in memory_init
    assert not (
        ROOT / "src/ai_karen_engine/core/personalization/goals/lifecycle.py"
    ).exists()
    assert not (
        ROOT / "src/ai_karen_engine/core/personalization/goals/prospective.py"
    ).exists()
    assert not (
        ROOT / "src/ai_karen_engine/core/memory/prospective/__init__.py"
    ).exists()


def test_open_loop_schema_is_migration_owned_and_rls_protected() -> None:
    migration = _text(
        "supabase/migrations/20261005020000_22_memory_open_loops.sql"
    )

    assert "CREATE TABLE IF NOT EXISTS public.memory_open_loop" in migration
    assert "REFERENCES public.memory_event(event_id) ON DELETE CASCADE" in migration
    assert "ALTER TABLE public.memory_open_loop ENABLE ROW LEVEL SECURITY" in migration


def test_semantic_user_model_schema_is_migration_owned_and_rls_protected() -> None:
    migration = _text(
        "supabase/migrations/20261005010000_21_memory_semantic_user_model.sql"
    )

    assert "CREATE TABLE IF NOT EXISTS public.memory_user_goal" in migration
    assert "CREATE TABLE IF NOT EXISTS public.memory_prospective_item" in migration
    assert "REFERENCES public.memory_event(event_id) ON DELETE CASCADE" in migration
    assert "ALTER TABLE public.memory_user_goal ENABLE ROW LEVEL SECURITY" in migration
    assert "ALTER TABLE public.memory_prospective_item ENABLE ROW LEVEL SECURITY" in migration


def test_goal_and_prospective_state_use_durable_memory_authority() -> None:
    goals_init = _text(
        "src/ai_karen_engine/core/personalization/goals/__init__.py"
    )
    memory_init = _text(
        "src/ai_karen_engine/core/memory/__init__.py"
    )
    projector = _text(
        "src/ai_karen_engine/platform/memory/postgres/derived_projector.py"
    )

    for retired in (
        "GoalLifecycle",
        "GoalStore",
        "ProspectiveMemoryManager",
        "ProspectiveMemoryStore",
        "IntentionLifecycle",
        "CommitmentLifecycle",
    ):
        assert retired not in goals_init
        assert retired not in memory_init

    assert "can_transition_goal" in projector
    assert "can_transition_prospective" in projector
    assert "MemoryUserGoal" in projector
    assert "MemoryProspectiveItem" in projector


def test_temporal_resolution_belongs_to_existing_memory_temporal_domain() -> None:
    temporal_init = _text(
        "src/ai_karen_engine/core/memory/temporal/__init__.py"
    )
    projector = _text(
        "src/ai_karen_engine/platform/memory/postgres/derived_projector.py"
    )

    assert "resolve_temporal_text" in temporal_init
    assert "from ai_karen_engine.core.memory.temporal import resolve_temporal_text" in projector
    assert not (
        ROOT / "src/ai_karen_engine/core/memory/temporal_resolver.py"
    ).exists()


def test_retired_ram_lifecycle_files_are_absent() -> None:
    retired_paths = (
        "src/ai_karen_engine/core/personalization/goals/lifecycle.py",
        "src/ai_karen_engine/core/personalization/goals/prospective.py",
        "src/ai_karen_engine/core/memory/prospective/__init__.py",
    )
    for relative in retired_paths:
        assert not (ROOT / relative).exists()


def test_continuity_contracts_have_single_memory_owner() -> None:
    memory_contracts = _text(
        "src/ai_karen_engine/core/memory/contracts.py"
    )
    goal_contracts = _text(
        "src/ai_karen_engine/core/personalization/goals/contracts.py"
    )

    assert memory_contracts.count("class ProspectiveMemory") == 1
    assert memory_contracts.count("class GoalState") == 1
    assert memory_contracts.count("class OpenLoopState") == 1
    assert "class ProspectiveMemory" not in goal_contracts
    assert "class GoalState" not in goal_contracts
    assert "from ai_karen_engine.core.memory.contracts import (" in goal_contracts


def test_open_loop_continuity_is_durable_private_and_recallable() -> None:
    migration = _text(
        "supabase/migrations/20261005020000_22_memory_open_loops.sql"
    )
    privacy = _text(
        "src/ai_karen_engine/services/privacy_compliance.py"
    )
    retriever = _text(
        "src/ai_karen_engine/platform/memory/postgres/user_state_retriever.py"
    )
    projector = _text(
        "src/ai_karen_engine/platform/memory/postgres/derived_projector.py"
    )

    assert "CREATE TABLE IF NOT EXISTS public.memory_open_loop" in migration
    assert "ALTER TABLE public.memory_open_loop ENABLE ROW LEVEL SECURITY" in migration
    assert '"memory_open_loop"' in privacy
    assert "MemoryOpenLoop" in retriever
    assert "unresolved_intention_relevance" in retriever
    assert 'signal.signal_type == "open_loop"' in projector
    assert 'signal.signal_type == "open_loop_transition"' in projector
    assert "can_transition_open_loop" in projector
