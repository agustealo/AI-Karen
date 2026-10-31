from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
API = ROOT / "src/ui_launchers/Karen-AI-Theme/src/lib/api.ts"
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotControlledChat.tsx"


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

    # Canonical CopilotKit renders a safe failure, never raw exception data.
    assert 'setError("Karen could not complete the request. Check the conversation history.");' in source
    assert 'role="alert"' in source
    assert "error.stack" not in source
    assert "error.message" not in source
