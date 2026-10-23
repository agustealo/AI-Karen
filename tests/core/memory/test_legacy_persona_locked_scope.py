"""Fail-closed tenant and principal scoping for locked legacy evidence reads."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
    verify_locked_legacy_migration_evidence,
)


@pytest.mark.asyncio
async def test_locked_legacy_evidence_requires_active_transaction():
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    with pytest.raises(PermissionError, match="active canonical migration"):
        await verify_locked_legacy_migration_evidence(
            session=session, tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()), source_record_id="source",
        )
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_locked_legacy_evidence_denies_mismatched_scope_before_sensitive_reads():
    tenant = str(uuid.uuid4())
    user = str(uuid.uuid4())
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    scope_result = MagicMock()
    scope_result.one.return_value = (str(uuid.uuid4()), tenant, user)
    session.execute = AsyncMock(return_value=scope_result)

    with pytest.raises(PermissionError, match="transaction principal mismatch"):
        await verify_locked_legacy_migration_evidence(
            session=session, tenant_id=tenant, user_id=user,
            source_record_id="source",
        )
    assert session.execute.await_count == 1
    assert "current_setting" in str(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_locked_legacy_evidence_denies_missing_authenticated_user_before_source_read():
    tenant = str(uuid.uuid4())
    user = str(uuid.uuid4())
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    scope_result = MagicMock()
    scope_result.one.return_value = (tenant, tenant, None)
    session.execute = AsyncMock(return_value=scope_result)

    with pytest.raises(PermissionError, match="transaction principal mismatch"):
        await verify_locked_legacy_migration_evidence(
            session=session, tenant_id=tenant, user_id=user,
            source_record_id="source",
        )
    assert session.execute.await_count == 1

@pytest.mark.asyncio
async def test_locked_payload_reader_denies_ineligible_source_before_content_query(monkeypatch):
    from ai_karen_engine.platform.memory.postgres import legacy_persona_source as source

    eligibility = AsyncMock(return_value=None)
    monkeypatch.setattr(source, "verify_locked_legacy_migration_evidence", eligibility)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=AssertionError("unauthorized content read"))
    result = await source.read_locked_legacy_migration_source_content(
        session=session, tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()), source_record_id=str(uuid.uuid4()),
    )
    assert result is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_payload_reader_rejects_source_drift(monkeypatch):
    from datetime import datetime, timezone
    from ai_karen_engine.platform.memory.postgres import legacy_persona_source as source

    tenant, user, source_id = (str(uuid.uuid4()) for _ in range(3))
    created = datetime.now(timezone.utc)
    monkeypatch.setattr(
        source, "verify_locked_legacy_migration_evidence",
        AsyncMock(return_value=(created, "semantic")),
    )
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock(
        one_or_none=MagicMock(return_value=MagicMock(
            content="sensitive historical content",
            created_at=created, memory_type="episodic",
        ))
    ))
    with pytest.raises(PermissionError, match="source changed"):
        await source.read_locked_legacy_migration_source_content(
            session=session, tenant_id=tenant,
            user_id=user, source_record_id=source_id,
        )
    assert session.execute.await_count == 1

@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", " LEGACY_PERSONA "),
        ("source", "Legacy_Persona"),
        ("source_type", " LEGACY_PERSONA "),
        ("consent_scope", " PERSONA-MEMORY-MIGRATION "),
    ],
)
def test_vault_rejects_noncanonical_historical_source_markers(field, value):
    """Formatting differences must not turn historical entries into ordinary writes."""
    from ai_karen_engine.core.memory.types import (
        MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryType,
    )
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError, PostgresNeuroVault,
    )

    custom = {"consent_scope": "memory.write"}
    source = "chat_user"
    if field == "source":
        source = value
    else:
        custom[field] = value
    entry = MemoryEntry(
        id=str(uuid.uuid4()), content="historical content",
        memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
        metadata=MemoryMetadata(
            tenant_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
            source=source, custom=custom,
        ),
    )
    with pytest.raises(
        NeuroVaultAuthorizationError,
        match="historical migration persistence is disabled",
    ):
        PostgresNeuroVault._require_non_historical_write(entry)

def test_historical_transaction_capability_rejects_forgery_and_reuse():
    from types import SimpleNamespace
    from ai_karen_engine.platform.memory.postgres.vault import (
        _HistoricalTransactionCapability,
        _HISTORICAL_CAPABILITY_WITNESS,
        _verify_historical_transaction_capability,
    )

    tenant, user, memory_id = (str(uuid.uuid4()) for _ in range(3))
    session = MagicMock()
    session.in_transaction.return_value = True
    context = SimpleNamespace(tenant_id=tenant, user_id=user)
    entry = SimpleNamespace(id=memory_id)
    args = dict(session=session, context=context, entry=entry)
    forged = _HistoricalTransactionCapability(
        nonce=object(), session=session, tenant=tenant,
        user=user, memory_id=memory_id,
    )
    assert not _verify_historical_transaction_capability(forged, **args)
    witness = _HistoricalTransactionCapability(
        nonce=_HISTORICAL_CAPABILITY_WITNESS, session=session,
        tenant=tenant, user=user, memory_id=memory_id,
    )
    assert not _verify_historical_transaction_capability(
        witness, session=MagicMock(), context=context, entry=entry,
    )
    assert not _verify_historical_transaction_capability(
        witness, session=session,
        context=SimpleNamespace(tenant_id=str(uuid.uuid4()), user_id=user),
        entry=entry,
    )
    assert not _verify_historical_transaction_capability(
        witness, session=session, context=context,
        entry=SimpleNamespace(id=str(uuid.uuid4())),
    )
    assert _verify_historical_transaction_capability(witness, consume=True, **args)
    assert not _verify_historical_transaction_capability(witness, **args)
