from __future__ import annotations

from pathlib import Path


CHAT_RUNTIME_PATH = Path("src/ai_karen_engine/core/runtime/chat_runtime.py")


def _chat_runtime_source() -> str:
    return CHAT_RUNTIME_PATH.read_text(encoding="utf-8")


def test_chat_runtime_plan_preserves_authorized_reasoning_modes_and_model_budget() -> None:
    source = _chat_runtime_source()

    assert "max_model_calls=decision.max_model_calls" in source
    assert "max_reasoning_steps=decision.max_steps" in source
    assert "reasoning_modes=list(decision.reasoning_modes)" in source
    assert "reasoning_modes=[decision.reasoning_depth]" not in source


def test_chat_runtime_reasoning_request_uses_activation_modes_not_capabilities() -> None:
    source = _chat_runtime_source()

    assert "get_runtime_reasoning_bridge().activate(" in source
    assert "reasoning_modes=list(activation.reasoning_modes)" in source
    assert "reasoning_modes=list(decision.required_capabilities)" not in source


def test_chat_runtime_charges_reasoning_execution_back_to_runtime_budget_meter() -> None:
    source = _chat_runtime_source()

    assert 'result.diagnostics.get("model_calls", 0)' in source
    assert "await meter.consume_model_call()" in source
    assert 'result.diagnostics.get("steps", 0)' in source
    assert "await meter.consume_reasoning_step()" in source


def test_reasoning_strategy_cannot_override_observed_model_receipt() -> None:
    """The dependency-light cognitive gate guards provenance construction."""
    import ast
    tree = ast.parse(_chat_runtime_source())
    run_reasoning = next(
        node for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "ChatRuntime"
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_reasoning"
    )
    receipt = next(
        node.value for node in ast.walk(run_reason)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "provider_meta" for target in node.targets)
    )
    assert isinstance(receipt, ast.Dict)
    fields = {
        key.value: value
        for key, value in zip(receipt.keys, receipt.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert isinstance(fields["actual_provider"], ast.Constant)
    assert fields["actual_provider"].value is None
    assert isinstance(fields["actual_model"], ast.Constant)
    assert fields["actual_model"].value is None
    assert isinstance(fields["response_source"], ast.Constant)
    assert fields["response_source"].value == "reasoning"
    # A configured strategy may describe its target, but its metadata must
    # never be spread over the canonical execution receipt.
    assert not any(
        isinstance(key, ast.Constant) and key.value in {"actual_provider", "actual_model"}
        and isinstance(value, ast.Call)
        for key, value in zip(receipt.keys, receipt.values)
    )
    exclusions = [
        comparison.comparators[0]
        for comparison in ast.walk(receipt)
        if isinstance(comparison, ast.Compare)
        and any(isinstance(op, ast.NotIn) for op in comparison.ops)
        and isinstance(comparison.left, ast.Name)
        and comparison.left.id == "key"
        and len(comparison.comparators) == 1
        and isinstance(comparison.comparators[0], ast.Set)
    ]
    assert exclusions, "Strategy metadata must exclude observed execution fields"
    excluded = {
        value.value
        for exclusion in exclusions
        for value in exclusion.elts
        if isinstance(value, ast.Constant)
    }
    assert {"actual_provider", "actual_model", "response_source"}.issubset(excluded)
