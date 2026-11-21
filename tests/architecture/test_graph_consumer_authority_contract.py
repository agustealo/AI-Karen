"""KIS-GRAPH-01C2N: prevent graph-candidate bypasses at external boundaries.

This is a static import/call contract, not an assertion that every dynamically
loaded consumer is known. PostgreSQL graph reads remain internal to retrieval;
NeuroRecall is the final memory-evidence selection and source ACL authority.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_IMPORTS = (
    "ai_karen_engine.core.memory.graph",
    "ai_karen_engine.platform.memory.postgres.graph_repository",
    "ai_karen_engine.core.memory.retrieval.retrieval_router",
)
BACKEND_CALLS = frozenset(
    {
        "get_leangraph_service",
        "get_entity_context",
        "get_related_context",
        "find_related_events",
        "find_entity_context",
        "project_memory_event",
    }
)
EXTERNAL_PYTHON_ROOTS = (
    "src/ai_karen_engine/api_routes",
    "src/ai_karen_engine/mcp",
    "src/ai_karen_engine/plugins",
    "src/ai_karen_engine/services/plugins",
    "plugins",
    "free_plugins",
)
UI_ROOT = ROOT / "src/ui_launchers/Karen-AI-Theme/src"
UI_BACKEND_IDENTIFIERS = frozenset(
    {"get_leangraph_service", "LeanGraphService", "PostgresGraphRepository"}
)


def _python_sources() -> list[Path]:
    sources: list[Path] = []
    for dirname in EXTERNAL_PYTHON_ROOTS:
        base = ROOT / dirname
        if base.is_dir():
            sources.extend(base.rglob("*.py"))
    return sorted(set(sources))


def _violations(source: Path) -> list[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(
                node.module == prefix or node.module.startswith(prefix + ".")
                for prefix in BACKEND_IMPORTS
            ):
                found.append(f"line {node.lineno}: direct import {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == prefix or alias.name.startswith(prefix + ".")
                    for prefix in BACKEND_IMPORTS
                ):
                    found.append(f"line {node.lineno}: direct import {alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if name in BACKEND_CALLS:
                found.append(f"line {node.lineno}: raw graph call {name}")
    return found


def test_external_python_boundaries_do_not_query_raw_memory_graph() -> None:
    findings: list[str] = []
    for source in _python_sources():
        for violation in _violations(source):
            findings.append(f"{source.relative_to(ROOT)}: {violation}")
    assert not findings, (
        "External consumers must use authenticated runtime NeuroRecall results, "
        "not direct GraphRepository or LeanGraphService candidate access: "
        + "; ".join(findings)
    )


def test_ui_does_not_reference_memory_graph_backend_implementation() -> None:
    if not UI_ROOT.is_dir():
        pytest.fail("expected Karen UI source directory is missing")
    findings: list[str] = []
    for extension in ("*.ts", "*.tsx"):
        for source in UI_ROOT.rglob(extension):
            data = source.read_text(encoding="utf-8")
            if any(identifier in data for identifier in UI_BACKEND_IDENTIFIERS):
                findings.append(source.relative_to(ROOT).as_posix())
    assert not findings, (
        "UI must display backend-selected memory evidence and not select "
        f"memory graph storage: {sorted(set(findings))}"
    )


def test_memory_graph_selection_and_search_graph_are_distinct_contracts() -> None:
    """A UI search provenance diagram is not a personal memory-graph read."""
    selected = (
        ROOT
        / "src/ai_karen_engine/core/memory/retrieval/selected_graph_projection.py"
    ).read_text(encoding="utf-8")
    internet = (
        ROOT / "src/ai_karen_engine/services/search/evidence_graph_projection.py"
    ).read_text(encoding="utf-8")
    assert "def project_selected_memory_graph(" in selected
    assert "RecallResult" in selected and "RecallRequest" in selected
    assert 'receipt.get("source") != "postgres_graph"' in selected
    assert 'provenance.get("graph_relationship") != "MENTIONS"' in selected
    assert "def project_search_evidence_graph(" in internet
    assert '"kind": "retrieval_evidence"' in internet
    assert '"kind": "selected_memory_graph"' in selected
