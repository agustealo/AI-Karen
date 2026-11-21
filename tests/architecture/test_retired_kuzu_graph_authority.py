"""KIS-GRAPH-01C2L: no direct Kuzu memory execution outside runtime authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.memory.graph.adapters import (
    GraphRepository,
    KuzuGraphAdapter,
    KuzuGraphUnavailableError,
)
from ai_karen_engine.core.memory.graph.config import LeanGraphConfig
from ai_karen_engine.core.memory.graph.service import LeanGraphService


def test_import_compatibility_without_legacy_implementation() -> None:
    assert KuzuGraphAdapter.__name__ == "KuzuGraphAdapter"
    assert GraphRepository is not None


@pytest.mark.parametrize("backend", ["postgres", "in_memory", "kuzu"])
def test_kuzu_cannot_be_constructed_even_with_supported_config(
    backend: str, tmp_path: Path,
) -> None:
    path = tmp_path / "unexpected-graph-directory"
    config = LeanGraphConfig(graph_backend=backend, graph_db_path=str(path))
    with pytest.raises(KuzuGraphUnavailableError, match="Kuzu memory graph backend is retired"):
        KuzuGraphAdapter(config)
    assert not path.exists()


def test_canonical_graph_service_rejects_kuzu() -> None:
    with pytest.raises(ValueError, match="kuzu is retired"):
        LeanGraphService(LeanGraphConfig(graph_backend="kuzu"))


def test_legacy_adapter_exposes_no_raw_graph_queries_or_mutations() -> None:
    for method in (
        "initialize", "upsert_memory_event", "upsert_entity",
        "upsert_assertion", "upsert_principal", "create_edge",
        "find_related_events", "find_entity_context", "close",
    ):
        assert method not in KuzuGraphAdapter.__dict__


def test_runtime_source_has_no_direct_kuzu_adapter_consumers() -> None:
    root = Path(__file__).resolve().parents[2]
    exceptions = {
        root / "src/ai_karen_engine/core/memory/graph/adapters/kuzu_adapter.py",
        root / "src/ai_karen_engine/core/memory/graph/adapters/__init__.py",
    }
    references: list[str] = []
    for dirname in ("src", "server", "scripts", "plugins", "free_plugins"):
        base = root / dirname
        if not base.is_dir():
            continue
        for source in base.rglob("*.py"):
            if source in exceptions:
                continue
            content = source.read_text(encoding="utf-8")
            if "KuzuGraphAdapter" in content or "kuzu_adapter" in content:
                references.append(source.relative_to(root).as_posix())
    assert not references, (
        "Direct legacy Kuzu consumers must migrate to canonical graph runtime: "
        f"{sorted(references)}"
    )
