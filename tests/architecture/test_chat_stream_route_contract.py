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
