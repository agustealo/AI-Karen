from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "src/ai_karen_engine/services/database/repositories/conversation_repository.py"
POSTGRES = ROOT / "src/ai_karen_engine/services/database/repositories/postgres_conversation_repository.py"
GATEWAY = ROOT / "src/ai_karen_engine/core/runtime/conversation_runtime_gateway.py"
ROUTES = ROOT / "src/ai_karen_engine/api_routes/chat/conversation.py"
MIGRATION = ROOT / "supabase/migrations/20261007070000_27_conversation_session_identity.sql"


def test_conversation_session_identity_is_a_first_class_repository_field() -> None:
    model = MODEL.read_text(encoding="utf-8")
    postgres = POSTGRES.read_text(encoding="utf-8")

    assert "session_id: Optional[str] = None" in model
    assert "(conversation_id, tenant_id, user_id, session_id, title, is_active," in postgres
    assert '"session_id": conversation.session_id' in postgres
    assert "AND session_id = :session_id" in postgres
    assert "conversation_metadata::jsonb ->> 'session_id'" not in postgres


def test_gateway_and_route_do_not_duplicate_session_identity_in_metadata() -> None:
    gateway = GATEWAY.read_text(encoding="utf-8")
    routes = ROUTES.read_text(encoding="utf-8")

    assert "session_id=context.session_id" in gateway
    create_block = gateway.split("Conversation(", 1)[1].split(")", 1)[0]
    assert '"session_id": context.session_id' not in create_block
    assert "session_id=conversation.session_id" in routes


def test_migration_backfills_then_removes_legacy_metadata_session_identity() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "SET session_id = NULLIF(conversation_metadata ->> 'session_id', '')" in migration
    assert "conversation_metadata = COALESCE(conversation_metadata, '{}'::jsonb) - 'session_id'" in migration
    assert "idx_conversations_tenant_user_session" in migration
