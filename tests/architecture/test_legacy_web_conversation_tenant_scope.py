from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/services/memory/conversation_service.py"


def test_legacy_web_conversation_queries_use_tenant_scope() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert (
        "from ai_karen_engine.database.id_types import (\n"
        "    coerce_tenant_id,\n"
        "    coerce_user_id as normalize_user_id,\n"
        ")" in source
    )
    assert source.count(
        "TenantConversation.tenant_id == coerce_tenant_id(tenant_id)"
    ) >= 12


def test_session_activity_uses_cached_authenticated_scope() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    block = source.split("async def update_session_activity", 1)[1].split(
        "async def get_user_active_sessions", 1
    )[0]

    assert 'tenant_id = session_info.get("tenant_id")' in block
    assert 'user_id = session_info.get("user_id")' in block
    assert "TenantConversation.tenant_id == coerce_tenant_id(tenant_id)" in block
    assert "TenantConversation.user_id == normalize_user_id(user_id)" in block
    assert ".where(TenantConversation.session_id == session_id)" not in block


def test_legacy_analytics_cannot_cross_tenant_scope() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    block = source.split("async def get_conversation_analytics", 1)[1].split(
        "async def _update_web_ui_conversation_fields", 1
    )[0]

    assert "TenantConversation.tenant_id == coerce_tenant_id(tenant_id)" in block

def test_legacy_user_scope_imports_the_canonical_id_coercion_owner() -> None:
    """The legacy adapter must not rely on a database-manager compatibility export."""
    source = SERVICE.read_text(encoding="utf-8")
    imports = source.split(
        "from ai_karen_engine.database.conversation_manager import (", 1
    )[1].split(")", 1)[0]

    assert "normalize_user_id" not in imports
    assert "coerce_user_id as normalize_user_id" in source
    assert "def normalize_user_id(" not in source

    from ai_karen_engine.database.id_types import coerce_user_id

    assert coerce_user_id("user-123") == coerce_user_id("user-123")
    assert coerce_user_id("user-123") != coerce_user_id("user-456")
