"""CK-27D source contracts for scoped requested-model UX.

Source-only proof; actual provider receipts require authenticated runtime tests.
"""
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx"
)


def test_model_request_cleared_on_conversation_identity_change() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    reset = source.split("  useEffect(() => {\n    setModelRequest(null);", 1)[1]
    assert "setManageOpen(false);" in reset
    assert "}, [currentSession?.id]);" in reset


def test_model_preference_is_not_presented_as_actual_executor() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'data-testid="karen-pending-model-preference"' in source
    assert "Requested for upcoming messages:" in source
    assert "Karen determines and reports the actual executor." in source
    assert "preferredProvider={modelRequest?.provider ?? null}" in source
    assert "preferredModel={modelRequest?.model ?? null}" in source
