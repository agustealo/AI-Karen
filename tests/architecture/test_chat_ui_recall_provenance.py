"""Recall provenance must be shown only from canonical backend-attested events."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat"
PROJECTION = ROOT / "src/ai_karen_engine/core/runtime/ag_ui_event_projection.py"
VERIFIED_HISTORY = CHAT / "copilotkit/KarenCopilotVerifiedHistory.tsx"
RECEIPTS = CHAT / "KarenVerifiedReceipts.tsx"


def test_chat_provenance_is_sourced_from_backend_metadata() -> None:
    history = VERIFIED_HISTORY.read_text(encoding="utf-8")
    projection = PROJECTION.read_text(encoding="utf-8")
    receipts = RECEIPTS.read_text(encoding="utf-8")

    assert 'name === "karen.response_integrity.v1"' in history
    assert "<KarenResponseIntegrity data={part.value} />" in history
    assert '"output_truncated", "cortex_intent", "personal_recall_grounded"' in history
    assert 'receipt.cortex_intent === "memory.recall"' in receipts
    assert 'receipt.personal_recall_grounded === true' in receipts
    assert 'meta.get("cortex_intent") == "memory.recall"' in projection
    assert '"authorized_memory_evidence"' in projection
    assert '"authorized_conversation_evidence"' in projection


def test_ui_does_not_infer_grounding_from_provider() -> None:
    history = VERIFIED_HISTORY.read_text(encoding="utf-8")
    receipts = RECEIPTS.read_text(encoding="utf-8")

    assert 'typeof value.personal_recall_grounded !== "boolean"' in history
    assert 'typeof receipt.personal_recall_grounded === "boolean"' in receipts
    assert 'receipt.actual_provider ===' not in receipts
    assert 'KarenResponseIntegrity' in history
    assert 'response_source' not in receipts.split("export function KarenResponseIntegrity", 1)[1].split(
        "export function KarenRestoredExecutionReceipt", 1
    )[0]
