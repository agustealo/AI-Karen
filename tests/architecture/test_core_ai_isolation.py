"""Hard isolation gates for the beta-critical Core AI execution perimeter.

Unlike the broader CORE-SPLIT-2 convergence inventory, these rules are not
xfail debt. Model runtime and expression execution must remain independently
importable and must never reach outward into integrations, extensions, plugins,
MCP implementations, API transports, or CopilotKit.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"
CORE_ROOT = SRC_ROOT / "core"
CRITICAL_ROOTS = (
    CORE_ROOT / "model_runtime",
    CORE_ROOT / "expression",
)
FORBIDDEN_PREFIXES = (
    "ai_karen_engine.integrations",
    "ai_karen_engine.extensions",
    "ai_karen_engine.plugins",
    "ai_karen_engine.mcp",
    "ai_karen_engine.api_routes",
    "copilotkit",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_beta_critical_core_never_imports_outer_layers() -> None:
    violations: list[tuple[str, str]] = []

    for root in CRITICAL_ROOTS:
        assert root.exists(), f"critical Core domain is missing: {root}"
        for path in root.rglob("*.py"):
            for imported in _imports(path):
                if any(
                    imported == prefix or imported.startswith(prefix + ".")
                    for prefix in FORBIDDEN_PREFIXES
                ):
                    violations.append((str(path.relative_to(SRC_ROOT)), imported))

    if violations:
        details = "\n".join(f"  {path}: {imported}" for path, imported in violations)
        pytest.fail(
            "Beta-critical Core AI execution leaked into an outer layer.\n"
            "Core must depend on ports/contracts; adapters depend inward on Core.\n"
            f"Violations:\n{details}"
        )


def test_provider_execution_port_is_stdlib_only() -> None:
    path = CORE_ROOT / "model_runtime" / "provider_execution.py"
    imports = _imports(path)
    allowed_roots = {"__future__", "collections", "threading", "typing"}
    forbidden = [
        imported
        for imported in imports
        if imported.split(".", 1)[0] not in allowed_roots
    ]

    assert not forbidden, (
        "provider execution port must stay dependency-free; found imports: "
        + ", ".join(forbidden)
    )
