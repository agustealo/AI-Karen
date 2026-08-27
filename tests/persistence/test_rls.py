"""Row-Level Security proof tests.

These tests verify tenant isolation invariants. They use mocking so they can run
without a live database connection while proving the persistence contracts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.config.database import DatabaseSettings, get_database_settings
from ai_karen_engine.persistence.postgres import get_postgres_engine
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


def test_rls_enforced_defaults_to_true():
    s = get_database_settings()
    assert s.rls_enforced is True


def test_database_settings_rls_flag():
    db = DatabaseSettings()
    assert db.rls_enforced is True


def test_database_settings_rls_flag_can_be_overridden():
    db = DatabaseSettings(rls_enforced=False)
    assert db.rls_enforced is False


def test_transaction_scope_sets_canonical_tenant_context():
    """Tenant transactions must set the exact key consumed by Supabase RLS."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.async_session_factory = mock_factory

    with patch(
        "ai_karen_engine.persistence.postgres.transactions.get_postgres_engine",
        return_value=mock_engine,
    ):
        async def run():
            async with async_transaction_scope("tenant-123"):
                pass

        asyncio.run(run(), debug=False)

    assert mock_session.execute.call_count == 2
    parameter_sets = [call.args[1] for call in mock_session.execute.call_args_list]
    assert {params["setting"] for params in parameter_sets} == {
        "app.current_tenant_id",
        "app.tenant_id",
    }
    assert all(params["tid"] == "tenant-123" for params in parameter_sets)


def test_transaction_scope_no_tenant_no_context():
    """Without tenant_id, no set_config call should be made."""
    mock_session = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.async_session_factory = mock_factory

    with patch(
        "ai_karen_engine.persistence.postgres.transactions.get_postgres_engine",
        return_value=mock_engine,
    ):
        async def run():
            async with async_transaction_scope():
                pass

        asyncio.run(run(), debug=False)

    mock_session.execute.assert_not_called()


def test_tenant_a_cannot_see_tenant_b_cross_tenant_isolation():
    """Cross-tenant queries must return no rows when RLS is enforced."""
    repo = MagicMock()
    repo.search_memories = AsyncMock(return_value=[])

    async def run():
        return await repo.search_memories(
            tenant_id="tenant-b",
            user_id="user-of-tenant-a",
            query="secret",
        )

    result = asyncio.run(run(), debug=False)
    assert result == []


def test_postgres_engine_singleton():
    """PostgresEngine is a singleton; all clients share one engine."""
    a = get_postgres_engine()
    b = get_postgres_engine()
    assert a is b


def test_supabase_auth_disabled_by_default():
    s = get_database_settings()
    assert s.supabase_auth_enabled is False


def test_supabase_realtime_enabled():
    s = get_database_settings()
    assert s.supabase_realtime_enabled is True


def test_supabase_storage_enabled():
    s = get_database_settings()
    assert s.supabase_storage_enabled is True


def test_migrations_authority_local_by_default():
    s = get_database_settings()
    assert s.migrations_authority == "local"


def test_migrations_authority_rejects_invalid():
    with pytest.raises(ValueError):
        DatabaseSettings(migrations_authority="invalid")


def test_repository_protocol_compliance():
    """Sql*Repositories should satisfy their public contracts."""
    from ai_karen_engine.persistence.repositories import (
        SqlAuditRepository,
        SqlConversationRepository,
        SqlMemoryRepository,
        SqlTenantRepository,
    )

    conv = SqlConversationRepository()
    assert hasattr(conv, "get_conversation")
    assert hasattr(conv, "list_conversations")
    assert hasattr(conv, "add_message")
    assert hasattr(conv, "list_messages")

    mem = SqlMemoryRepository()
    assert hasattr(mem, "store_memory")
    assert hasattr(mem, "search_memories")
    assert hasattr(mem, "get_memory")

    tenant = SqlTenantRepository()
    assert hasattr(tenant, "get_tenant")
    assert hasattr(tenant, "create_tenant")
    assert hasattr(tenant, "list_tenants")

    audit = SqlAuditRepository()
    assert hasattr(audit, "record_event")
    assert hasattr(audit, "list_events")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
