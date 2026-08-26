"""Architecture guards for MEMORY-CONVERGENCE-4C."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEMORY = ROOT / "src" / "ai_karen_engine" / "core" / "memory"
PLATFORM_POSTGRES = ROOT / "src" / "ai_karen_engine" / "platform" / "memory" / "postgres"


def test_legacy_recall_manager_is_retired() -> None:
    assert not (MEMORY / "retrieval" / "recall_manager.py").exists()


def test_legacy_core_postgres_adapter_is_retired() -> None:
    assert not (MEMORY / "adapters" / "postgres_adapter.py").exists()


def test_legacy_recall_adapter_exports_are_retired() -> None:
    source = (MEMORY / "adapters" / "__init__.py").read_text(encoding="utf-8")
    assert "LegacyRecallManagerAdapter" not in source
    assert "LegacyMemoryServiceAdapter" not in source
    assert "recall_manager" not in source


def test_postgres_durable_retriever_lives_in_platform() -> None:
    source = (PLATFORM_POSTGRES / "recall_retriever.py").read_text(encoding="utf-8")
    assert "class PostgresRecallRetriever" in source
    assert "async def recall" in source
    assert "MemoryAssertion.tenant_id == tenant_uuid" in source
    assert "MemoryAssertion.user_id == user_uuid" in source
    assert "MemoryAssertion.consent_state == \"granted\"" in source


def test_neuro_recall_is_the_source_fusion_authority() -> None:
    source = (MEMORY / "retrieval" / "neuro_recall.py").read_text(encoding="utf-8")
    assert "asyncio.gather" in source
    assert "partial_retrieval_failure" in source
    assert "class RecallManager" not in source


def test_runtime_composes_postgres_behind_neuro_recall() -> None:
    source = (MEMORY / "memory_runtime_manager.py").read_text(encoding="utf-8")
    assert "PostgresRecallRetriever" in source
    assert "NeuroRecall(" in source
    assert "select(MemoryAssertion)" not in source
    assert ".ilike(" not in source


def test_canonical_write_base_contains_no_database_recall_fallback() -> None:
    source = (MEMORY / "_memory_runtime_base.py").read_text(encoding="utf-8")
    assert "select(MemoryAssertion)" not in source
    assert "Recall service failed, falling back" not in source
    assert "Retrieval adapter failed, falling back" not in source
    assert "write runtime base cannot recall" in source


def test_old_mature_impl_is_explicitly_quarantined() -> None:
    legacy = MEMORY / "_legacy_memory_runtime_impl.py"
    assert legacy.exists()
    canonical = (MEMORY / "memory_runtime_manager.py").read_text(encoding="utf-8")
    assert "_legacy_memory_runtime_impl" not in canonical
