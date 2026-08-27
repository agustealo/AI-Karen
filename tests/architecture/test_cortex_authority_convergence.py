from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_cortex_executive_is_owned_by_core_cortex() -> None:
    source = _source("core/cortex/executive.py")
    tree = ast.parse(source)
    classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "CortexExecutionDecider" in classes
    assert "get_cortex_execution_decider" in functions


def test_runtime_cortex_decider_path_is_compatibility_only() -> None:
    source = _source("core/runtime/cortex_execution_decider.py")
    tree = ast.parse(source)

    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    assert "ai_karen_engine.core.cortex.executive" in _imports(source)
    assert "Compatibility import" in source


def test_core_cortex_exports_canonical_executive() -> None:
    source = _source("core/cortex/__init__.py")
    assert "CortexExecutionDecider" in source
    assert "get_cortex_execution_decider" in source
    assert "ai_karen_engine.core.cortex.executive" in _imports(source)


def test_legacy_dispatch_declares_compatibility_status() -> None:
    source = _source("core/cortex/dispatch.py")
    assert "Legacy CORTEX decision-package compatibility surface" in source
    assert "must not evolve into a second execution authority" in source


def test_intelligence_runtime_does_not_execute_runtime_capabilities() -> None:
    imports = _imports(_source("core/intelligence/intelligence_runtime.py"))
    forbidden_prefixes = (
        "ai_karen_engine.core.expression.gateway",
        "ai_karen_engine.core.langgraph_orchestrator",
        "ai_karen_engine.agent_medusa",
        "ai_karen_engine.extensions",
    )

    offenders = sorted(
        imported
        for imported in imports
        if imported.startswith(forbidden_prefixes)
    )
    assert offenders == []


def test_runtime_control_plane_is_operational_not_cognitive() -> None:
    source = _source("core/runtime/chat_runtime_control_plane.py")
    imports = _imports(source)

    assert not any(
        imported.startswith("ai_karen_engine.core.cortex")
        or imported.startswith("ai_karen_engine.core.intelligence")
        for imported in imports
    )
    assert "class RuntimeMode" in source
    assert "class ChatRuntimeControlPlane" in source
