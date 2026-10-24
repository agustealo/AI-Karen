"""Read-only, tenant-scoped lookup of canonical NeuroVault replay evidence.

This adapter does not grant permissions, import legacy records or bypass RLS.
Callers must supply a verified principal and a deterministic expected memory ID.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from ai_karen_engine.core.memory.legacy_persona_recovery import (
    LegacyReplayReceiptEvidence,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import MemoryAssertion, MemoryEvent


async def lookup_legacy_replay_receipt(
    *, tenant_id: str, user_id: str, expected_memory_id: str,
    expected_request_id: str,
) -> LegacyReplayReceiptEvidence:
    tenant = uuid.UUID(tenant_id)
    user = uuid.UUID(user_id)
    expected = uuid.UUID(expected_memory_id)
    request = uuid.UUID(expected_request_id)
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
        return await lookup_locked_legacy_replay_receipt(
            session=session, tenant_id=tenant_id, user_id=user_id,
            expected_memory_id=expected_memory_id,
            expected_request_id=expected_request_id,
        )


async def lookup_locked_legacy_replay_receipt(
    *, session: "AsyncSession", tenant_id: str, user_id: str,
    expected_memory_id: str, expected_request_id: str,
) -> LegacyReplayReceiptEvidence:
    """Inspect the canonical receipt inside an existing transaction.

    Does not commit, authorize migration or import source data.
    """
    tenant = uuid.UUID(tenant_id)
    user = uuid.UUID(user_id)
    expected = uuid.UUID(expected_memory_id)
    request = uuid.UUID(expected_request_id)
    # Lock the deterministic assertion slot, including when no receipt exists.
    # This prevents two prospective migration executors from both treating
    # an absent row as an independently available replay identity.
    from sqlalchemy import text
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot, 0))"),
        {"slot": f"persona-migration-replay:{tenant}:{user}:{expected}"},
    )
    result = await session.execute(
        select(MemoryAssertion, MemoryEvent)
        .join(MemoryEvent, MemoryAssertion.event_id == MemoryEvent.event_id)
        .where(
            MemoryAssertion.assertion_id == expected,
            MemoryAssertion.tenant_id == tenant,
            MemoryAssertion.user_id == user,
            MemoryEvent.tenant_id == tenant,
            MemoryEvent.user_id == user,
        )
        .with_for_update(of=(MemoryAssertion, MemoryEvent))
    )
    match = result.one_or_none()
    if match is None:
        return LegacyReplayReceiptEvidence(
            expected_memory_id=str(expected), expected_tenant_id=str(tenant),
            expected_user_id=str(user), persisted_memory_id=None,
            persisted_tenant_id=None, persisted_user_id=None, persisted=False,
        )
    assertion, event = match
    vault_payload = (event.payload or {}).get("vault")
    provenance_valid = (
        isinstance(vault_payload, dict)
        and vault_payload.get("request_id") == str(request)
    )
    return LegacyReplayReceiptEvidence(
        expected_memory_id=str(expected), expected_tenant_id=str(tenant),
        expected_user_id=str(user),
        persisted_memory_id=str(assertion.assertion_id),
        persisted_tenant_id=str(event.tenant_id),
        persisted_user_id=str(event.user_id),
        persisted=(provenance_valid and event.event_type == "memory_persisted"
                   and assertion.valid_to is None),
    )
