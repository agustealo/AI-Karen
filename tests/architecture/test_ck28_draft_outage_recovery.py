"""CK-28A: do not bypass canonical draft persistence during a 503 outage."""
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/useKarenPersistedDraft.ts"
CHAT = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotControlledChat.tsx"


def test_only_transient_503_retries_automatically() -> None:
    source = HOOK.read_text(encoding="utf-8")
    assert 'status !== "unavailable" || failureStatus !== 503' in source
    assert 'document.visibilityState === "visible"' in source
    assert 'window.clearTimeout(timer)' in source
    assert 'retry()' in source


def test_chat_still_requires_verified_durable_draft_clear_before_send() -> None:
    source = CHAT.read_text(encoding="utf-8")
    assert '!draftSynced || submitPending.current' in source
    assert 'if (!await clearBeforeSubmit(text)' in source
    assert 'agent.addMessage({' in source
