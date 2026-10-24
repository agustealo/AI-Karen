"""Canonical assistant-ui must render only runtime-attested recall grounding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat"
PROJECTION = ROOT / "src/ai_karen_engine/core/runtime/ag_ui_event_projection.py"


def test_chat_provenance_is_sourced_from_backend_metadata():
    chat = (UI / "assistant-ui/KarenAssistantChat.tsx").read_text(encoding="utf-8")
    projection = PROJECTION.read_text(encoding="utf-8")
    assert '"karen.response_integrity.v1": KarenResponseIntegrity' in chat
    assert 'receipt.cortex_intent === "memory.recall"' in chat
    assert 'receipt.personal_recall_grounded === true' in chat
    assert 'meta.get("cortex_intent") == "memory.recall"' in projection
    assert '"authorized_memory_evidence"' in projection
    assert '"authorized_conversation_evidence"' in projection


def test_ui_does_not_infer_grounding_from_provider():
    chat = (UI / "assistant-ui/KarenAssistantChat.tsx").read_text(encoding="utf-8")
    assert 'typeof receipt.personal_recall_grounded === "boolean"' in chat
    assert 'receipt.actual_provider ===' not in chat
