"""Consumer UI must show runtime-grounded personal recall provenance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat"


def test_chat_provenance_is_sourced_from_backend_metadata():
    chat = (UI / "ChatInterface.tsx").read_text(encoding="utf-8")
    panel = (UI / "RuntimeMetadataPanel.tsx").read_text(encoding="utf-8")
    for source_key, prop in (
        ("cortex_intent", "cortexIntent"),
        ("cortex_reason_codes", "cortexReasonCodes"),
        ("personal_evidence_attribute", "personalEvidenceAttribute"),
        ("personal_recall_grounded", "personalRecallGrounded"),
        ("evidence_count", "evidenceCount"),
    ):
        assert f"metadata.{source_key}" in chat
        assert f"{prop}={{latestAssistantMetadata.{prop}}}" in chat
        assert prop in panel

    assert "CORTEX intent" in panel
    assert "Personal evidence attribute" in panel
    assert "Personal recall grounded" in panel
    assert "CORTEX reasons:" in panel
    assert "data-testid=\"cortex-reason-codes\"" in panel


def test_ui_does_not_infer_grounding_from_provider():
    chat = (UI / "ChatInterface.tsx").read_text(encoding="utf-8")
    assert "typeof metadata.personal_recall_grounded === 'boolean'" in chat
