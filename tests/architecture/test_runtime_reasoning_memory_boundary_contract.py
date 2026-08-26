"""Architecture gates for Runtime reasoning-mode and memory-write boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"
CHAT_RUNTIME = CORE / "runtime" / "chat_runtime.py"
RUNTIME_CONTRACTS = CORE / "runtime" / "contracts.py"
EXECUTION_DECISION = CORE / "runtime" / "execution_decision.py"
REASONING_CONTRACTS = CORE / "reasoning" / "contracts.py"


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


def test_reasoning_mode_boundary_is_closed_and_legacy_alias_is_explicit() -> None:
    source = _source(REASONING_CONTRACTS)

    assert "def normalize_reasoning_modes" in source
    assert "unsupported reasoning mode" in source
    assert '"reasoning": ReasoningMode.EVIDENCE_SYNTHESIS.value' in source
    assert "Compatibility shim for the legacy ChatRuntime call site" in source


def test_legacy_chat_runtime_reasoning_wiring_is_contained_until_migrated() -> None:
    chat = _source(CHAT_RUNTIME)
    runtime_contracts = _source(RUNTIME_CONTRACTS)
    reasoning_contracts = _source(REASONING_CONTRACTS)

    plan_method = chat.split("def _build_authorized_plan", 1)[1].split(
        "async def _run_simple", 1
    )[0]
    reasoning_method = chat.split("async def _run_reasoning", 1)[1].split(
        "async def _run_reasoning_stream", 1
    )[0]

    canonical_plan = "reasoning_modes=list(decision.reasoning_modes)" in plan_method
    canonical_request = "reasoning_modes=list(decision.reasoning_modes)" in reasoning_method

    if not canonical_plan:
        assert "reasoning_modes=[decision.reasoning_depth]" in plan_method
        assert "pre-typed ChatRuntime plan builder" in runtime_contracts
        assert 'raw_modes == ["deep"]' in runtime_contracts
        assert '"evidence_synthesis"' in runtime_contracts

    if not canonical_request:
        assert "reasoning_modes=list(decision.required_capabilities)" in reasoning_method
        assert "legacy ChatRuntime call site" in reasoning_contracts
        assert '"reasoning": ReasoningMode.EVIDENCE_SYNTHESIS.value' in reasoning_contracts


def test_canonical_reasoning_result_bridges_legacy_summary_read() -> None:
    source = _source(REASONING_CONTRACTS)
    assert "def summary(self) -> str" in source
    assert "return self.conclusion" in source
    assert "Deprecated compatibility view" in source


def test_authorized_memory_write_is_not_silently_lost_by_legacy_recall_coupling() -> None:
    chat = _source(CHAT_RUNTIME)
    decision = _source(EXECUTION_DECISION)

    canonical_execute = "if decision.memory_write_allowed:" in chat.split(
        "async def execute(", 1
    )[1].split("async def execute_stream", 1)[0]

    if not canonical_execute:
        assert "compat_memory_write_requires_recall" in decision
        assert "if self.memory_write_allowed and not self.memory_recall_required" in decision
        assert "Authorization still comes exclusively from RuntimePolicy" in decision


def test_execution_requirements_memory_write_default_is_fail_closed() -> None:
    defaults = _class_defaults(RUNTIME_CONTRACTS, "ExecutionRequirements")
    assert defaults["memory_write_allowed"] is False
