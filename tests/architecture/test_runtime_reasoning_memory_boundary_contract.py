"""Architecture gates for Runtime reasoning-mode and memory-write boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"
CHAT_RUNTIME = CORE / "runtime" / "chat_runtime.py"
RUNTIME_CONTRACTS = CORE / "runtime" / "contracts.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _class_defaults(path: Path, class_name: str) -> dict[str, object]:
    tree = ast.parse(_source(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        defaults: dict[str, object] = {}
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            if item.value is None:
                continue
            try:
                defaults[item.target.id] = ast.literal_eval(item.value)
            except (ValueError, TypeError):
                continue
        return defaults
    raise AssertionError(f"class not found: {class_name}")


def test_chat_runtime_authorized_plan_uses_typed_reasoning_modes() -> None:
    source = _source(CHAT_RUNTIME)
    method = source.split("def _build_authorized_plan", 1)[1].split(
        "async def _run_simple", 1
    )[0]

    assert "reasoning_modes=list(decision.reasoning_modes)" in method
    assert "reasoning_modes=[decision.reasoning_depth]" not in method


def test_chat_runtime_reasoning_request_does_not_use_capability_names_as_modes() -> None:
    source = _source(CHAT_RUNTIME)
    method = source.split("async def _run_reasoning", 1)[1].split(
        "async def _run_reasoning_stream", 1
    )[0]

    assert "reasoning_modes=list(decision.reasoning_modes)" in method
    assert "reasoning_modes=list(decision.required_capabilities)" not in method
    assert '["synthesis"]' not in method


def test_chat_runtime_memory_persistence_is_independent_of_recall() -> None:
    source = _source(CHAT_RUNTIME)
    execute = source.split("async def execute(", 1)[1].split(
        "async def execute_stream", 1
    )[0]
    stream = source.split("async def execute_stream", 1)[1].split(
        "# ------------------------------------------------------------------\n    # Memory", 1
    )[0]

    assert "if decision.memory_write_allowed:" in execute
    assert "if decision.memory_recall_required:" not in execute.split(
        "if fallback is not None and fallback.answer:", 1
    )[1].split("return fallback", 1)[0]
    assert "if decision.memory_write_allowed:" in stream
    assert "decision.memory_recall_required and decision.memory_write_allowed" not in stream


def test_execution_requirements_memory_write_default_is_fail_closed() -> None:
    defaults = _class_defaults(RUNTIME_CONTRACTS, "ExecutionRequirements")
    assert defaults["memory_write_allowed"] is False
