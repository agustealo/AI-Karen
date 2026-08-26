"""Architecture gates for cognitive authority convergence.

These tests prevent retired orchestration authority from reappearing inside Core
reasoning and ensure CORTEX has one verification-policy owner.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine" / "core"
REASONING = CORE / "reasoning"
SELECTOR = CORE / "cortex" / "behavior" / "selector.py"
DEFAULTS = REASONING / "defaults.py"
REASONING_INIT = REASONING / "__init__.py"


def _python_sources(root: Path) -> list[tuple[Path, str]]:
    return [
        (path, path.read_text(encoding="utf-8", errors="strict"))
        for path in root.rglob("*.py")
    ]


def test_kro_shadow_runtime_files_are_retired() -> None:
    assert not (REASONING / "kro_orchestrator.py").exists()
    assert not (REASONING / "strategies" / "kro_strategy.py").exists()


def test_default_reasoning_path_has_no_kro_authority() -> None:
    source = DEFAULTS.read_text(encoding="utf-8")
    assert "KROReasoningStrategy" not in source
    assert "kro_orchestrator" not in source


def test_reasoning_public_surface_has_no_kro_exports() -> None:
    source = REASONING_INIT.read_text(encoding="utf-8")
    assert '"KROOrchestrator"' not in source
    assert '"get_kro_orchestrator"' not in source
    assert '"KROReasoningStrategy"' not in source
    assert "core.reasoning.kro_orchestrator" not in source
    assert "strategies.kro_strategy" not in source


def test_no_python_module_imports_retired_kro_runtime() -> None:
    violations: list[str] = []
    for path, source in _python_sources(CORE):
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            violations.append(f"{path.relative_to(CORE)}: syntax error: {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "reasoning.kro_orchestrator" in module or "reasoning.strategies.kro_strategy" in module:
                    violations.append(f"{path.relative_to(CORE)} imports {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "reasoning.kro_orchestrator" in alias.name or "reasoning.strategies.kro_strategy" in alias.name:
                        violations.append(f"{path.relative_to(CORE)} imports {alias.name}")

    assert not violations, "Retired KRO authority is still referenced: " + "; ".join(violations)


def test_behavior_selector_delegates_verification_policy() -> None:
    source = SELECTOR.read_text(encoding="utf-8")
    tree = ast.parse(source)

    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_evaluate_verification" not in methods
    assert "VerificationDecider" in source
    assert "verification_decider.decide" in source
