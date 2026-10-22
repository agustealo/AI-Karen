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
) -> LegacyReplayReceiptEvidence:
    tenant = uuid.UUID(tenant_id)
    user = uuid.UUID(user_id)
    expected = uuid.UUID(expected_memory_id)
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
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
        )
        match = result.one_or_none()
    if match is None:
        return LegacyReplayReceiptEvidence(
            expected_memory_id=str(expected), expected_tenant_id=str(tenant),
            expected_user_id=str(user), persisted_memory_id=None,
            persisted_tenant_id=None, persisted_user_id=None, persisted=False,
        )
    assertion, event = match
    return LegacyReplayReceiptEvidence(
        expected_memory_id=str(expected), expected_tenant_id=str(tenant),
        expected_user_id=str(user),
        persisted_memory_id=str(assertion.assertion_id),
        persisted_tenant_id=str(event.tenant_id),
        persisted_user_id=str(event.user_id),
        persisted=event.event_type == "memory_persisted" and assertion.valid_to is None,
    )
