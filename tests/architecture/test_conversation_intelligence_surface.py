from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
RAIL = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"
)


def test_stream_terminal_metadata_exposes_turn_intelligence_truth() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        '"memory_context": dict(',
        '"memory_candidate_count": int(',
        '"memory_admitted_count": int(',
        '"memory_persisted_count": int(',
        '"memory_formation_status": memory_recall_meta.get(',
        '"intent": decision.intent',
        '"intent_confidence": decision.intent_confidence',
    ):
        assert token in source


def test_conversation_intelligence_uses_terminal_provider_truth() -> None:
    source = RAIL.read_text(encoding="utf-8")

    assert "normalizeExecutionUsage(agentSteps, metadata || {})" in source
    assert "const actualProvider = asString(responseMetadata.actual_provider)" in source
    assert "const actualModel = asString(responseMetadata.actual_model)" in source
    assert "Context recalled (" in source
    assert "Learning this turn" in source
    assert "Turn understanding" in source
    assert "No tool, plugin, or provider activity has been reported for this turn." in source
