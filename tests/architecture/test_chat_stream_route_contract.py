from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
CHAT_UI = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx"
)


def test_chat_stream_frontend_and_backend_share_one_canonical_route() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    routers = ROUTERS.read_text(encoding="utf-8")
    chat_ui = CHAT_UI.read_text(encoding="utf-8")

    assert '@router.post("/chat/stream")' in runtime
    assert 'RouterSpec(chat_runtime_router, "/api", ("chat-runtime",))' in routers
    assert "apiClient.postStream(" in chat_ui
    assert ": '/api/chat/stream'" in chat_ui
    assert '@router.post("/stream")' not in runtime


def test_chat_stream_telemetry_reports_the_canonical_route() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert 'endpoint="/api/chat/stream"' in runtime
    assert '"endpoint": "/api/chat/stream"' in runtime
    assert 'endpoint="/api/stream"' not in runtime
    assert '"endpoint": "/api/stream"' not in runtime


def test_both_production_chat_transports_delegate_to_canonical_runtime() -> None:
    """HTTP and SSE must share runtime decisions and memory-grounded output."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "result = await get_chat_runtime().execute(runtime_request)" in runtime
    assert "async for chunk in get_chat_runtime().execute_stream(runtime_request)" in runtime
    assert "response_metadata = result.metadata.to_dict()" in runtime
    assert "metadata=response_metadata" in runtime
    assert "chunk.to_sse_payload()" in runtime


def test_both_runtime_modes_offer_grounded_answer_before_model_execution() -> None:
    """No generated biography may replace canonical authorized profile evidence."""
    core = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    assert core.count("grounded = self._grounded_personal_response(") >= 2
    assert "if grounded is not None and not self._is_explicit_save_turn(request):" in core
    assert "actual_model\": None" in core
