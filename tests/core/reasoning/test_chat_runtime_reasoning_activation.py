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
