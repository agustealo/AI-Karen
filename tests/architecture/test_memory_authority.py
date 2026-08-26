from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"
MEMORY_ROOT = CORE_ROOT / "memory"


def test_legacy_core_recall_authority_is_retired() -> None:
    """Production recall authority must live under the canonical memory domain."""
    assert not (CORE_ROOT / "recall").exists()
    assert (MEMORY_ROOT / "retrieval").is_dir()


def test_neuro_memory_architecture_declares_single_owners() -> None:
    architecture = (MEMORY_ROOT / "NEURO_MEMORY_ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )

    assert "MemoryRuntimeManager" in architecture
    assert "NeuroRecall" in architecture
    assert "NeuroVault" in architecture
    assert "NeuroRecall never stores" in architecture
    assert "NeuroVault never decides recall" in architecture


def test_memory_readme_rejects_retired_backend_assumptions() -> None:
    readme = (MEMORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Milvus and Elasticsearch are not part of the current memory architecture" in readme
    assert "production recall behavior belongs behind `core/memory/retrieval/`" in readme
