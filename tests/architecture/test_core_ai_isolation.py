"""Hard isolation gates for the Core AI execution perimeter.

The live execution spine is zero-tolerance: no integrations, extensions,
plugins, MCP implementations, API transports, or CopilotKit imports. Older
model-runtime modules that still violate the boundary are held in an exact debt
inventory so the set can only shrink, never silently grow.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"
CORE_ROOT = SRC_ROOT / "core"
MODEL_RUNTIME_ROOT = CORE_ROOT / "model_runtime"
EXPRESSION_ROOT = CORE_ROOT / "expression"
FORBIDDEN_PREFIXES = (
    "ai_karen_engine.integrations",
    "ai_karen_engine.extensions",
    "ai_karen_engine.plugins",
    "ai_karen_engine.mcp",
    "ai_karen_engine.api_routes",
    "copilotkit",
)

ACTIVE_EXECUTION_FILES = (
    MODEL_RUNTIME_ROOT / "provider_execution.py",
    MODEL_RUNTIME_ROOT / "provider_contracts.py",
    MODEL_RUNTIME_ROOT / "provider_registry_service.py",
    MODEL_RUNTIME_ROOT / "provider_policy.py",
    MODEL_RUNTIME_ROOT / "provider_endpoint.py",
    MODEL_RUNTIME_ROOT / "model_manager.py",
    MODEL_RUNTIME_ROOT / "providers" / "transformers_runtime.py",
    MODEL_RUNTIME_ROOT / "providers" / "vllm_runtime.py",
)

# Exact pre-existing debt outside the beta execution spine. This is not an
# allow-anything wildcard: any new file/import pair makes CI fail. Remove entries
# as each legacy module is migrated or deleted after reference audit.
KNOWN_LEGACY_VIOLATIONS = {
    ("core/model_runtime/model_store.py", "ai_karen_engine.integrations.registry"),
    (
        "core/model_runtime/routing/intelligent_model_router.py",
        "ai_karen_engine.integrations.registry",
    ),
    (
        "core/model_runtime/routing/llm_router_service.py",
        "ai_karen_engine.integrations.llm_utils",
    ),
    (
        "core/model_runtime/routing/llm_router_service.py",
        "ai_karen_engine.integrations.llm_registry",
    ),
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _outer_layer_violations(paths: list[Path]) -> set[tuple[str, str]]:
    violations: set[tuple[str, str]] = set()
    for path in paths:
        for imported in _imports(path):
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.add((str(path.relative_to(SRC_ROOT)), imported))
    return violations


def _production_model_runtime_files() -> list[Path]:
    return [
        path
        for path in MODEL_RUNTIME_ROOT.rglob("*.py")
        if "tests" not in path.parts
    ]


def test_active_core_execution_spine_never_imports_outer_layers() -> None:
    paths = list(ACTIVE_EXECUTION_FILES) + list(EXPRESSION_ROOT.rglob("*.py"))
    missing = [path for path in paths if not path.exists()]
    assert not missing, f"critical Core files missing: {missing}"

    violations = _outer_layer_violations(paths)
    if violations:
        details = "\n".join(
            f"  {path}: {imported}" for path, imported in sorted(violations)
        )
        pytest.fail(
            "Active Core AI execution leaked into an outer layer.\n"
            "Core must depend on ports/contracts; adapters depend inward on Core.\n"
            f"Violations:\n{details}"
        )


def test_no_untracked_model_runtime_outer_imports() -> None:
    actual = _outer_layer_violations(_production_model_runtime_files())
    unexpected = actual - KNOWN_LEGACY_VIOLATIONS
    resolved = KNOWN_LEGACY_VIOLATIONS - actual

    if unexpected:
        details = "\n".join(
            f"  {path}: {imported}" for path, imported in sorted(unexpected)
        )
        pytest.fail(
            "New untracked Core model-runtime boundary violations detected.\n"
            f"Violations:\n{details}"
        )

    # Force the debt inventory to shrink when code is fixed. A stale entry is a
    # test failure so cleanup cannot be completed without updating this ledger.
    if resolved:
        details = "\n".join(
            f"  {path}: {imported}" for path, imported in sorted(resolved)
        )
        pytest.fail(
            "Core isolation debt was resolved but the inventory was not reduced.\n"
            f"Remove these stale entries:\n{details}"
        )


def test_provider_execution_port_is_stdlib_only() -> None:
    path = MODEL_RUNTIME_ROOT / "provider_execution.py"
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
