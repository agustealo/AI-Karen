from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONVERSATION_ROUTES = (
    ROOT
    / "src/ai_karen_engine/api_routes/chat/conversation.py"
)


def test_conversation_routes_use_stdlib_compatible_exception_logging() -> None:
    routes = CONVERSATION_ROUTES.read_text(encoding="utf-8")

    assert 'error=str(error)' not in routes
    assert 'extra={"error_type": type(error).__name__}' in routes


def test_list_conversations_keeps_original_exception_visible() -> None:
    routes = CONVERSATION_ROUTES.read_text(encoding="utf-8")
    block = routes.split("async def list_conversations", 1)[1].split(
        "@router.post(\"/create\"", 1
    )[0]

    assert 'logger.exception(' in block
    assert '"Failed to list conversations"' in block
    assert 'extra={"error_type": type(error).__name__}' in block
