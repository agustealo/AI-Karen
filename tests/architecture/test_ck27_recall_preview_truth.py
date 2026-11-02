"""CK-27F: memory preview labels must not imply all recalled items are visible."""
from pathlib import Path

RAIL = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"


def test_recall_preview_reports_visible_count_and_reported_total() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "Recalled context preview (" in source
    assert "Math.min(turnIntelligence.recalled.length, 4)" in source
    assert "of ${turnIntelligence.recallCount} reported" in source
    assert "turnIntelligence.recalled.slice(0, 4)" in source
    assert "Context recalled ({turnIntelligence.recallCount})" not in source
