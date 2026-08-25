from __future__ import annotations

"""Hard architectural quarantine for Karen's Core AI machine.

Outer capabilities may depend on Core contracts and register adapters at the
composition edge. Core must never import concrete integrations, extensions,
plugins, MCP implementations, HTTP routes, or UI/copilot infrastructure.
"""

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
CORE_ROOT = SRC_ROOT / "ai_karen_engine" / "core"

FORBIDDEN_OUTER_PREFIXES = (
    "ai_karen_engine.integrations",
    "ai_karen_engine.extensions",
    "ai_karen_engine.plugins",
    "ai_karen_engine.mcp",
    "ai_karen_engine.api_routes",
    "ai_karen_engine.copilotkit",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_core_ai_machine_has_no_outer_extension_imports() -> None:
    """Core is an inner machine: outer adapters depend inward, never reverse."""
    assert CORE_ROOT.exists(), f"Core root missing: {CORE_ROOT}"

    violations: list[tuple[str, str]] = []
    for path in CORE_ROOT.rglob("*.py"):
        if not path.is_file():
            continue
        for imported in _imports(path):
            if imported.startswith(FORBIDDEN_OUTER_PREFIXES):
                violations.append((str(path.relative_to(SRC_ROOT)), imported))

    if violations:
        details = "\n".join(
            f"  {path}: {imported}" for path, imported in sorted(violations)
        )
        pytest.fail(
            "Core AI Machine isolation breached. Concrete outer capabilities "
            "must be injected/registered at the composition edge, not imported "
            f"by Core.\nViolations:\n{details}"
        )


def test_model_execution_path_is_explicitly_integration_free() -> None:
    """Protect the beta response path even if Core grows new subdomains later."""
    protected_roots = (
        CORE_ROOT / "expression",
        CORE_ROOT / "model_runtime",
        CORE_ROOT / "runtime",
        CORE_ROOT / "cortex",
    )
    violations: list[tuple[str, str]] = []
    for root in protected_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith(FORBIDDEN_OUTER_PREFIXES):
                    violations.append((str(path.relative_to(SRC_ROOT)), imported))

    assert not violations, (
        "Beta model execution path imports outer extension infrastructure:\n"
        + "\n".join(f"  {path}: {imported}" for path, imported in violations)
    )
