from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "src/ai_karen_engine/database/models/__init__.py"
MANAGER = ROOT / "src/ai_karen_engine/database/conversation_manager.py"


def test_tenant_conversation_orm_exposes_real_tenant_scope() -> None:
    models = MODELS.read_text(encoding="utf-8")

    block = models.split("class TenantConversation(Base):", 1)[1].split(
        "class TenantMemoryItem", 1
    )[0]
    assert "tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)" in block
    assert 'Index("idx_conversation_tenant_user", "tenant_id", "user_id")' in block


def test_legacy_message_persistence_never_synthesizes_identity() -> None:
    manager = MANAGER.read_text(encoding="utf-8")

    assert 'default="default"' not in manager
    assert 'or "anonymous"' not in manager
    assert 'raise ValueError("tenant_id is required to persist a conversation message")' in manager
    assert 'raise ValueError("user_id is required to persist a conversation message")' in manager


def test_legacy_conversation_crud_is_tenant_scoped() -> None:
    manager = MANAGER.read_text(encoding="utf-8")

    assert "TenantConversation.tenant_id == normalized_tenant_id" in manager
    assert "TenantConversation.tenant_id == coerce_tenant_id(tenant_id)" in manager
    assert manager.count("TenantConversation.tenant_id == coerce_tenant_id(tenant_id)") >= 4
