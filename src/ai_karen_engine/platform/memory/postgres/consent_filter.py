"""Canonical PostgreSQL consent/validity predicate for all memory-event reads.

NeuroVault records the scoped consent grant at formation time. Revoking that
scope later must immediately suppress every candidate derived from the event,
without deleting the immutable evidence ledger. The same predicate is shared
by all PostgreSQL recall adapters and event-reference expansion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, true

from .ledger_models import ConsentScope, MemoryEvent


def recallable_memory_event(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime,
):
    """Return tenant/user and current consent restrictions for MemoryEvent.

    An absent scope row means no explicit revocation, as in NeuroVault's
    canonical write-consent policy. Legacy ledger events without a vault
    consent-scope annotation use the canonical memory.write scope. A revoked
    scope is checked at SQL selection time, before candidate ranking and LIMIT.
    """
    event_consent_scope = func.coalesce(
        MemoryEvent.payload["vault"]["consent_scope"].astext,
        "memory.write",
    )
    current_consent = (
        select(ConsentScope.is_granted)
        .where(
            ConsentScope.tenant_id == tenant_id,
            ConsentScope.user_id == user_id,
            ConsentScope.scope_name == event_consent_scope,
        )
        .order_by(
            ConsentScope.granted_at.desc(),
            ConsentScope.scope_id.desc(),
        )
        .limit(1)
        .correlate(MemoryEvent)
        .scalar_subquery()
    )
    return and_(
        MemoryEvent.tenant_id == tenant_id,
        MemoryEvent.user_id == user_id,
        MemoryEvent.consent_state == "granted",
        or_(MemoryEvent.valid_from.is_(None), MemoryEvent.valid_from <= now),
        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
        func.coalesce(current_consent, true()),
    )


__all__ = ["recallable_memory_event"]
