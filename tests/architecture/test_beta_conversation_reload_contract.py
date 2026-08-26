from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONVERSATION_ROUTE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "chat" / "conversation.py"
CHAT_ROUTE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "chat" / "runtime.py"
ROUTERS = ROOT / "server" / "routers.py"


def test_canonical_conversation_reload_is_tenant_and_user_scoped() -> None:
    source = CONVERSATION_ROUTE.read_text(encoding="utf-8")

    assert '@router.get("/by-session/{session_id}"' in source
    assert "get_web_ui_conversation_by_session(" in source
    assert "tenant_id=tenant_id" in source
    assert 'user_id=user_ctx.get("user_id")' in source
    assert "get_current_tenant_id" in source
    assert "bypass_user_context_func" in source


def test_canonical_conversation_router_is_mounted_for_beta_reload() -> None:
    source = ROUTERS.read_text(encoding="utf-8")

    assert "conversation_router" in source
    assert 'prefix="/api/conversations"' in source


def test_beta_reload_must_not_depend_on_legacy_chat_session_surface() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    # The legacy chat-session endpoints are transitional and currently do not
    # implement durable conversation retrieval. Beta persistence proof must use
    # /api/conversations/by-session/{session_id} instead.
    assert '@router.get("/sessions/{session_id}")' in source
    assert "Chat session retrieval is not implemented on the production orchestrator" in source
