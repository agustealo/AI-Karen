"""CK-28A: a draft outage must not replace the native conversation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit"
CHAT = ROOT / "KarenCopilotControlledChat.tsx"


def test_draft_outage_renders_contextual_recovery_beside_native_chat() -> None:
    source = CHAT.read_text(encoding="utf-8")
    assert "const recoveryPanel = draftStatus ===" in source
    assert "{recoveryPanel}" in source
    assert "<CopilotChatView" in source
    assert 'aria-label="Draft recovery"' in source
    assert "if (draftStatus === \"conflict\" || draftStatus === \"unavailable\") {" not in source
    assert "karen-unsynced-draft" not in source


def test_unsaved_draft_cannot_be_sent() -> None:
    source = CHAT.read_text(encoding="utf-8")
    assert '!draftSynced || submitPending.current' in source
    assert '!await clearBeforeSubmit(text)' in source
    assert 'agent.addMessage({' in source
