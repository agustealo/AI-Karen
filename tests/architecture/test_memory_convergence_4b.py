"""Architecture guards for MEMORY-CONVERGENCE-4B."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"
MEMORY = CORE / "memory"


def test_top_level_core_neuro_recall_is_retired():
    assert not (CORE / "neuro_recall").exists()
    assert (ROOT / "labs" / "memory" / "neuro_recall").exists()


def test_canonical_neuro_recall_exists_under_memory_retrieval():
    service = MEMORY / "retrieval" / "neuro_recall.py"
    text = service.read_text(encoding="utf-8")
    assert "class NeuroRecall" in text
    assert "class RecallScopeError" in text
    assert "tenant_id is required for memory recall" in text
    assert "user_id is required for memory recall" in text


def test_memory_runtime_has_no_direct_database_recall_fallback():
    text = (MEMORY / "memory_runtime_manager.py").read_text(encoding="utf-8")
    assert "select(MemoryAssertion)" not in text
    assert "ilike(" not in text
    assert "NeuroRecall" in text
    assert "await self._neuro_recall.recall" in text


def test_protocols_are_backend_neutral_and_define_vault_port():
    text = (MEMORY / "protocols.py").read_text(encoding="utf-8")
    for stale_name in ("Milvus", "Elasticsearch", "FAISS", "DuckDB"):
        assert stale_name not in text
    assert "class VaultPort" in text
    assert "class VaultContext" in text
    assert "async def persist" in text
    assert "async def tombstone" in text
    assert "async def verify_integrity" in text


def test_legacy_recall_manager_is_not_the_canonical_service():
    init_text = (MEMORY / "retrieval" / "__init__.py").read_text(encoding="utf-8")
    assert '"NeuroRecall"' in init_text
    assert '"RecallManager"' not in init_text
