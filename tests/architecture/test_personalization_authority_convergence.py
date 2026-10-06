from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_personalization_runtime_requires_explicit_repository() -> None:
    runtime = _text("src/ai_karen_engine/core/personalization/runtime.py")

    assert "repository: PersonalizationRepository" in runtime
    assert "requires an explicit repository" in runtime
    assert "PersonalizationRepository()" not in runtime


def test_personalization_repository_is_a_port_not_a_ram_database() -> None:
    repository = _text(
        "src/ai_karen_engine/core/personalization/persistence/repository.py"
    )

    assert "class PersonalizationRepository(ABC)" in repository
    assert "_preferences" not in repository
    assert "_behaviors" not in repository
    assert "_goals" not in repository
    assert "_current_states" not in repository


def test_platform_repository_reads_user_state_from_canonical_memory() -> None:
    repository = _text(
        "src/ai_karen_engine/platform/personalization/repository.py"
    )

    assert "FROM public.profile_fact pf" in repository
    assert "FROM public.memory_user_goal g" in repository
    assert "JOIN public.memory_event me" in repository
    assert "me.consent_state = 'granted'" in repository
    assert "save_preference" not in repository
    assert "save_goal" not in repository


def test_behavior_learning_is_durable_and_tenant_scoped() -> None:
    repository = _text(
        "src/ai_karen_engine/platform/personalization/repository.py"
    )
    migration = _text(
        "supabase/migrations/20261005030000_23_personalization_behavior_patterns.sql"
    )
    privacy = _text("src/ai_karen_engine/services/privacy_compliance.py")

    assert "personalization_behavior_pattern" in repository
    assert "async_transaction_scope(tenant_id=tenant)" in repository
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert '"personalization_behavior_pattern"' in privacy


def test_obsolete_process_local_model_stores_are_gone() -> None:
    memory_init = _text("src/ai_karen_engine/core/memory/__init__.py")

    for name in ("UserModelStore", "RelationshipModelStore", "SelfModelStore"):
        assert name not in memory_init

    for path in (
        "src/ai_karen_engine/core/memory/user_model/__init__.py",
        "src/ai_karen_engine/core/memory/relationship_model/__init__.py",
        "src/ai_karen_engine/core/memory/self_model/__init__.py",
    ):
        assert not (ROOT / path).exists()


def test_behavior_aggregator_has_no_process_local_pattern_store() -> None:
    aggregator = _text(
        "src/ai_karen_engine/core/personalization/behavior/aggregator.py"
    )
    contracts = _text(
        "src/ai_karen_engine/core/personalization/behavior/contracts.py"
    )

    assert "BehaviorPatternStore" not in aggregator
    assert "BehaviorPatternStore" not in contracts


def test_obsolete_personalization_adapter_is_removed() -> None:
    assert not (
        ROOT / "src/ai_karen_engine/core/personalization/adapters.py"
    ).exists()


def test_live_chat_runtime_feeds_governed_behavior_learning() -> None:
    composition = _text("src/ai_karen_engine/core/runtime/composition.py")
    chat = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert "user_model_runtime: UserModelRuntime | None = None" in composition
    assert "build_user_model_runtime()" in composition
    assert "_record_user_behavior_observation" in chat
    assert "decision.memory_write_allowed" in chat
    assert "provider_meta" not in chat.split(
        "async def _record_user_behavior_observation",
        1,
    )[1].split("def _build_authorized_plan", 1)[0]


def test_behavior_observation_ledger_is_durable_deduplicated_and_private() -> None:
    repository = _text("src/ai_karen_engine/platform/personalization/repository.py")
    migration = _text(
        "supabase/migrations/20261006020000_25_personalization_behavior_observations.sql"
    )
    privacy = _text("src/ai_karen_engine/services/privacy_compliance.py")

    assert "personalization_behavior_observation" in repository
    assert "ON CONFLICT (" in repository
    assert "observation_count =" in repository
    assert "personalization_behavior_pattern.observation_count + 1" in repository
    assert "PRIMARY KEY (tenant_id, user_id, observation_id)" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert '"personalization_behavior_observation"' in privacy


def test_behavior_observer_does_not_persist_raw_chat_content() -> None:
    chat = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")
    observer = chat.split(
        "async def _record_user_behavior_observation",
        1,
    )[1].split("def _build_authorized_plan", 1)[0]

    assert "request.messages" not in observer
    assert '"source": "chat.user_request"' in observer
    assert "context_signature" in observer
    assert "hashlib.sha256" in observer
