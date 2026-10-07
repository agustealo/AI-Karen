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


def test_conversation_intelligence_deck_surfaces_native_runtime_instruments() -> None:
    source = RAIL.read_text(encoding="utf-8")

    for token in (
        "Conversation Intelligence",
        "Runtime dispatch",
        "System resources",
        "Guardrails & capabilities",
        "Execution trace",
        "Provenance & persistence",
        "Human attention",
        "/api/system/resources",
        "resources live",
        "GPU / VRAM",
        "transcript_persistence_status",
        "trajectory_id",
    ):
        assert token in source


def test_conversation_resource_polling_is_desktop_scoped() -> None:
    source = RAIL.read_text(encoding="utf-8")

    assert "window.matchMedia('(min-width: 1280px)')" in source
    assert "window.setInterval" in source
    assert "15000" in source


def test_conversation_intelligence_surfaces_authorized_execution_envelope() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    rail = RAIL.read_text(encoding="utf-8")

    for token in (
        '"execution_budget": {',
        '"max_model_calls": plan.budget.max_model_calls',
        '"max_tool_calls": plan.budget.max_tool_calls',
        '"max_reasoning_steps": plan.budget.max_reasoning_steps',
        '"max_output_tokens": plan.budget.max_output_tokens',
        '"reasoning_modes": list(plan.reasoning_modes)',
    ):
        assert token in runtime

    for token in (
        "Execution envelope",
        "Model calls",
        "Tool calls",
        "Reasoning steps",
        "Output budget",
        "resumable",
    ):
        assert token in rail
