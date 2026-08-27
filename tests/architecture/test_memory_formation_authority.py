"""Architecture contracts for canonical memory formation evaluation."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEMORY = ROOT / "src" / "ai_karen_engine" / "core" / "memory"
FORMATION = MEMORY / "formation"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(module)
            imported.update(f"{module}.{alias.name}" for alias in node.names)
    return imported


def test_only_formation_evaluator_owns_signal_and_worthiness_authorities() -> None:
    evaluator_imports = _imports(FORMATION / "evaluator.py")
    assert "ai_karen_engine.core.memory.scoring.MemoryWorthinessScorer" in evaluator_imports
    assert "ai_karen_engine.core.memory.signals.get_signal_pipeline" in evaluator_imports

    for path in (
        FORMATION / "service.py",
        MEMORY / "shadow_evaluator.py",
        MEMORY / "memory_runtime_manager.py",
    ):
        imports = _imports(path)
        assert "ai_karen_engine.core.memory.scoring.MemoryWorthinessScorer" not in imports
        assert "ai_karen_engine.core.memory.signals.get_signal_pipeline" not in imports


def test_shadow_and_durable_formation_consume_canonical_evaluator() -> None:
    service = _source(FORMATION / "service.py")
    shadow = _source(MEMORY / "shadow_evaluator.py")
    runtime = _source(MEMORY / "memory_runtime_manager.py")

    assert "self._evaluator.evaluate(" in service
    assert "self._evaluator.evaluate(" in shadow
    assert "self._formation_evaluator = formation_evaluator or MemoryFormationEvaluator()" in runtime
    assert "self._formation_evaluator," in runtime
    assert "MemoryShadowEvaluator(\n            self._formation_evaluator\n        )" in runtime


def test_shadow_adapter_contains_no_durable_mutation_or_projection_authority() -> None:
    shadow = _source(MEMORY / "shadow_evaluator.py")
    lowered = shadow.casefold()

    assert "neurovault" not in lowered
    assert "vault.persist" not in lowered
    assert "derived_projector" not in lowered
    assert "projectionmanager" not in lowered
    assert "get_signal_pipeline" not in shadow
    assert "MemoryWorthinessScorer" not in shadow


def test_formation_evaluator_is_backend_neutral() -> None:
    imports = _imports(FORMATION / "evaluator.py")
    forbidden_prefixes = (
        "ai_karen_engine.platform",
        "ai_karen_engine.persistence",
        "sqlalchemy",
        "redis",
    )
    assert not any(
        imported.startswith(prefix)
        for imported in imports
        for prefix in forbidden_prefixes
    )
