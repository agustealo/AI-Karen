"""CK-27H: runtime evidence presentation must not invent executor attribution."""
from pathlib import Path

RAIL = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"


def test_runtime_engine_is_not_displayed_as_actual_model() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "{runtime.actualModel || 'No model reported'}" in source
    assert "runtime.actualModel || runtime.runtimeEngine" not in source
    assert "{runtime.runtimeEngine}" in source


def test_absent_degradation_flag_does_not_claim_healthy_execution() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "runtime.degradedMode ? 'degraded' : 'degradation not reported'" in source
    assert "runtime.degradedMode ? 'degraded' : 'healthy'" not in source
