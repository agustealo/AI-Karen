from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
API = ROOT / "src/ui_launchers/Karen-AI-Theme/src/lib/api.ts"
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotControlledChat.tsx"
ERROR_PRESENTATION = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat/const/getDegradedResponseMessage.tsx"


def test_runtime_stream_error_chunk_carries_safe_failure_metadata() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert '"error_code": "CHAT_GENERATION_FAILED"' in source
    assert '"error_type": type(exc).__name__' in source
    assert '"correlation_id": ctx.correlation_id' in source


def test_stream_client_forwards_error_metadata() -> None:
    source = API.read_text(encoding="utf-8")

    assert "onError?: (message: string, metadata?: Record<string, unknown>) => void;" in source
    assert "callbacks?.onError?.(parsed.content, parsed.metadata);" in source


def test_chat_ui_surfaces_error_type_and_correlation_without_traceback() -> None:
    source = UI.read_text(encoding="utf-8")

    # Canonical CopilotKit delegates to one allowlisted error presenter.
    # A literal generic sentence is not the contract: user-facing diagnostics
    # must distinguish canonical run codes without leaking raw exceptions.
    presentation = ERROR_PRESENTATION.read_text(encoding="utf-8")
    assert "getCopilotRunFailureMessage(failure)" in source
    assert 'role="alert"' in source
    assert "RUN_FAILURE_GUIDANCE" in presentation
    assert "CHAT_GENERATION_FAILED" in presentation
    assert "CHAT_TRANSCRIPT_PERSISTENCE_FAILED" in presentation
    assert "verified conversation history before retrying" in presentation
    assert "error.stack" not in source
    assert "error.message" not in source
    assert "return error.message" not in presentation.split(
        "export function getCopilotRunFailureMessage", 1
    )[1]
