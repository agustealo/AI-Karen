"""CK-27J: tool/plugin trace metadata is not proof of successful execution."""
from pathlib import Path

RAIL = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"


def test_tool_and_plugin_activity_discloses_proof_limit() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "usage.tools.length > 0 || usage.plugins.length > 0" in source
    assert "Tool and plugin names are reported in agent-step metadata." in source
    assert "Their presence does not confirm successful execution." in source
    assert "usage.tools.map((tool)" in source
    assert "usage.plugins.map((plugin)" in source
