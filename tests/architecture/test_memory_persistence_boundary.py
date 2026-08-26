from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_MEMORY = ROOT / "src" / "ai_karen_engine" / "core" / "memory"
INTEGRATION_MEMORY = ROOT / "src" / "ai_karen_engine" / "integrations" / "memory"

CORE_COMPAT = (
    CORE_MEMORY / "unified_memory_service.py",
    CORE_MEMORY / "_legacy_memory_runtime_impl.py",
    CORE_MEMORY / "profile_synthesis" / "profile_service.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_cognitive_core_memory_has_no_sqlalchemy_persistence_imports() -> None:
    for path in CORE_MEMORY.rglob("*.py"):
        for module in _imports(path):
            assert not (module == "sqlalchemy" or module.startswith("sqlalchemy.")), (
                f"cognitive Core memory must remain storage-neutral: {path} imports {module}"
            )


def test_legacy_core_persistence_paths_are_explicit_compatibility_surfaces() -> None:
    for path in CORE_COMPAT:
        source = path.read_text(encoding="utf-8-sig")
        assert "compatibility" in source.lower()
        assert "sqlalchemy" not in source.lower()
        assert "ai_karen_engine.integrations.memory" in source


def test_concrete_sql_persistence_lives_outside_cognitive_core() -> None:
    unified = INTEGRATION_MEMORY / "unified_memory_service.py"
    legacy = INTEGRATION_MEMORY / "legacy_memory_runtime_impl.py"
    profile = INTEGRATION_MEMORY / "profile_service.py"

    assert unified.exists()
    assert legacy.exists()
    assert profile.exists()
    assert "sqlalchemy" in unified.read_text(encoding="utf-8-sig").lower()
    assert "sqlalchemy" in legacy.read_text(encoding="utf-8-sig").lower()
    assert "sqlalchemy" in profile.read_text(encoding="utf-8-sig").lower()


def test_compatibility_bridges_do_not_define_new_memory_logic() -> None:
    bridge_paths = (
        INTEGRATION_MEMORY / "ledger_models.py",
        INTEGRATION_MEMORY / "scoring.py",
        INTEGRATION_MEMORY / "signals.py",
        INTEGRATION_MEMORY / "projections.py",
        INTEGRATION_MEMORY / "types.py",
        INTEGRATION_MEMORY / "neuro" / "activation_gate.py",
        INTEGRATION_MEMORY / "retrieval" / "retrieval_router.py",
    )
    for path in bridge_paths:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        assert not any(isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body)
        assert "ai_karen_engine.core.memory" in source
