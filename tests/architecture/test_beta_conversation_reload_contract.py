from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONVERSATION_ROUTE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "chat" / "conversation.py"
CHAT_ROUTE = ROOT / "src" / "ai_karen_engine" / "api_routes" / "chat" / "runtime.py"
ROUTERS = ROOT / "src" / "ai_karen_engine" / "server" / "routers.py"


def test_canonical_conversation_reload_is_tenant_and_user_scoped() -> None:
    source = CONVERSATION_ROUTE.read_text(encoding="utf-8")

    assert '@router.get("/by-session/{session_id}"' in source
    assert "get_web_ui_conversation_by_session(" in source
    assert "tenant_id=tenant_id" in source
    assert "user_id = _require_user_id(user_ctx)" in source
    assert "user_id=user_id" in source
    assert "get_current_tenant_id" in source
    assert "bypass_user_context_func" in source


def test_canonical_conversation_router_is_mounted_for_beta_reload() -> None:
    source = ROUTERS.read_text(encoding="utf-8")

    assert "conversation_router" in source
    assert 'prefix="/api/conversations"' in source


def test_beta_reload_must_not_depend_on_legacy_chat_session_surface() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    # Durable reload belongs only to the conversation authority. The canonical
    # chat ingress must not reintroduce a parallel session-retrieval surface.
    assert '@router.get("/sessions/{session_id}")' not in source
    assert "Chat session retrieval is not implemented on the production orchestrator" not in source
