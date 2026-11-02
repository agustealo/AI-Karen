"""CK-27E: attested activity absence message stays viewport-scoped."""
from pathlib import Path

RAIL = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx"


def test_mobile_notice_is_confined_to_mobile_disclosure() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert 'data-testid="karen-copilot-mobile-intelligence"' in source
    assert "xl:hidden" in source
    assert '<ConversationContextRail metadata={receipt} agentSteps={agentSteps} embedded />{agentSteps.length === 0 && <ActivityReplayNotice />}' in source


def test_desktop_notice_is_hidden_from_mobile_viewports() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert 'agentSteps.length === 0 && <div className="hidden xl:block"><ActivityReplayNotice /></div>' in source
    assert '<ConversationContextRail metadata={receipt} agentSteps={agentSteps} />{agentSteps.length === 0 && <ActivityReplayNotice />}' not in source
