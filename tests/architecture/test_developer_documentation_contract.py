from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "PROJECT_DEV_MANIFEST.md"
DEV_DOCS = REPO_ROOT / "docs" / "development"

REQUIRED_DOCS = (
    "README.md",
    "ARCHITECTURE_AUTHORITY.md",
    "STACK_APIS_FILE_STRUCTURE.md",
    "CORTEX_RUNTIME.md",
    "MEMORY.md",
    "REASONING_LANGGRAPH_MEDUSA.md",
    "EXTENSIONS_TOOLS.md",
    "SECURITY_OBSERVABILITY.md",
    "REPOSITORY_ENGINEERING.md",
    "TESTING_RELEASE.md",
)


def test_canonical_project_developer_manifest_exists() -> None:
    source = MANIFEST.read_text(encoding="utf-8")

    assert "# AI KAREN Project Developer Manifest" in source
    assert "CORTEX decides; Runtime executes" in source
    assert "ai_karen_engine.app:create_app" in source
    assert "ActionExecutionGate" in source
    assert "AgentMedusa" in source
    assert "LangGraph" in source


def test_required_developer_docs_exist() -> None:
    for filename in REQUIRED_DOCS:
        assert (DEV_DOCS / filename).is_file(), filename


def test_memory_docs_do_not_restore_retired_vector_stores() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    memory = (DEV_DOCS / "MEMORY.md").read_text(encoding="utf-8")

    assert "Milvus and Elasticsearch are not part" in manifest
    assert "Milvus and Elasticsearch are retired" in memory


def test_manifest_locks_provider_and_graph_boundaries() -> None:
    source = MANIFEST.read_text(encoding="utf-8")

    assert "`builtin_vllm` resurrection" in source
    assert "Use LangGraph only for true graph semantics" in source
    assert "Medusa does **not** own provider/model routing" in source


def test_documentation_index_links_every_subsystem_contract() -> None:
    index = (DEV_DOCS / "README.md").read_text(encoding="utf-8")

    for filename in REQUIRED_DOCS[1:]:
        assert filename in index
