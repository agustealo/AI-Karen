from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "src/ai_karen_engine/api_routes/chat/conversation.py"


def test_conversation_routes_have_one_durable_authority() -> None:
    routes = ROUTES.read_text(encoding="utf-8")

    assert "ConversationRuntimeGateway" in routes
    assert "get_conversation_runtime_gateway" in routes
    assert "get_conversation_service" not in routes
    assert "ConversationService" not in routes
    assert "get_conversation_analytics" not in routes
    assert "base_manager.get_conversation_stats" not in routes


def test_retired_legacy_conversation_analytics_routes_do_not_reappear() -> None:
    routes = ROUTES.read_text(encoding="utf-8")

    assert '@router.get("/analytics"' not in routes
    assert '@router.get("/stats"' not in routes
