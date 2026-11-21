"""Canonical PostgreSQL source expansion for memory-event references."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Mapping, Any

from sqlalchemy import or_, select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .consent_filter import recallable_memory_event
from .ledger_models import (
    MemoryAssertion, MemoryEvent, MemoryOpenLoop, MemoryProspectiveItem,
    MemoryUserGoal, ProfileFact,
)
from .procedural_models import MemoryProcedure


class PostgresEventSourceScopeError(ValueError):
    """Raised when event expansion lacks valid tenant/user scope."""


class PostgresEventSource:
    """Expand governed memory-event IDs back to canonical ledger rows."""

    async def fetch_many(
        self,
        *,
        tenant_id: str,
        user_id: str,
        event_ids: Iterable[str],
    ) -> dict[str, dict]:
        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
            user_uuid = uuid.UUID(str(user_id))
        except ValueError as exc:
            raise PostgresEventSourceScopeError("tenant_id and user_id must be valid UUIDs") from exc

        ids: list[uuid.UUID] = []
        for value in event_ids:
            try:
                parsed = uuid.UUID(str(value))
            except ValueError:
                continue
            if parsed not in ids:
                ids.append(parsed)
        if not ids:
            return {}

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            stmt = select(MemoryEvent).where(
                MemoryEvent.event_id.in_(ids),
                recallable_memory_event(
                    tenant_id=tenant_uuid, user_id=user_uuid,
                    now=datetime.now(timezone.utc).replace(tzinfo=None),
                ),
            )
            rows = (await session.execute(stmt)).scalars().all()

        return {
            str(row.event_id): {
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "payload": row.payload,
                "confidence": float(row.confidence or 0.0),
                "valid_from": row.valid_from,
                "valid_to": row.valid_to,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "source_type": row.source_type,
                "source_ref": row.source_ref,
            }
            for row in rows
        }


    async def authorize_selected_records(
        self,
        *,
        tenant_id: str,
        user_id: str,
        origins: Iterable[Mapping[str, Any]],
    ) -> bool:
        """Verify selected record revisions and live event consent as one read.

        A returned True proves only the current PostgreSQL snapshot. It is not
        a lease against later revocation and must never certify streamed bytes.
        Missing revisions, unknown kinds and unavailable storage fail closed.
        """
        try:
            tenant = uuid.UUID(str(tenant_id))
            user = uuid.UUID(str(user_id))
        except (TypeError, ValueError) as exc:
            raise PostgresEventSourceScopeError(
                "tenant_id and user_id must be valid UUIDs"
            ) from exc

        selections = list(origins)
        if not selections:
            return True
        if len(selections) > 50:
            return False

        record_types = {
            "memory_assertion": (MemoryAssertion, MemoryAssertion.assertion_id, MemoryAssertion.event_id),
            "profile_fact": (ProfileFact, ProfileFact.fact_id, ProfileFact.event_id),
            "memory_procedure": (MemoryProcedure, MemoryProcedure.procedure_id, MemoryProcedure.source_event_id),
            "memory_user_goal": (MemoryUserGoal, MemoryUserGoal.goal_id, MemoryUserGoal.event_id),
            "memory_open_loop": (MemoryOpenLoop, MemoryOpenLoop.open_loop_id, MemoryOpenLoop.event_id),
            "memory_prospective_item": (MemoryProspectiveItem, MemoryProspectiveItem.prospective_id, MemoryProspectiveItem.event_id),
            "memory_event": (MemoryEvent, MemoryEvent.event_id, MemoryEvent.event_id),
        }
        prepared = []
        for origin in selections:
            if not isinstance(origin, Mapping):
                return False
            record_type = origin.get("record_type")
            contract = record_types.get(record_type)
            revision = origin.get("record_updated_at")
            if contract is None or not isinstance(revision, str):
                return False
            try:
                record_id = uuid.UUID(str(origin["record_id"]))
                event_id = uuid.UUID(str(origin["event_id"]))
                parsed = datetime.fromisoformat(revision)
                if parsed.tzinfo is None:
                    return False
                updated_at = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, KeyError):
                return False
            if str(record_id) != origin["record_id"] or str(event_id) != origin["event_id"]:
                return False
            if record_type == "memory_event" and record_id != event_id:
                return False
            prepared.append((contract, record_type, record_id, event_id, updated_at))

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # All proofs are evaluated in a single scoped transaction. No read
        # grants authorization to future inference after this transaction.
        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            for (model, record_column, event_column), kind, record_id, event_id, revision in prepared:
                predicate = [
                    record_column == record_id,
                    event_column == event_id,
                    model.tenant_id == tenant,
                    model.user_id == user,
                    model.updated_at == revision,
                    recallable_memory_event(
                        tenant_id=tenant, user_id=user, now=now,
                    ),
                ]
                if kind != "memory_event":
                    predicate.extend((
                        or_(model.valid_from.is_(None), model.valid_from <= now),
                        or_(model.valid_to.is_(None), model.valid_to > now),
                    ))
                if kind == "memory_assertion":
                    predicate.append(MemoryAssertion.consent_state == "granted")
                elif kind == "memory_procedure":
                    predicate.append(MemoryProcedure.lifecycle_state == "active")
                elif kind == "memory_user_goal":
                    predicate.append(MemoryUserGoal.lifecycle_state.in_(
                        ("active", "blocked", "paused", "at_risk")
                    ))
                elif kind == "memory_open_loop":
                    predicate.append(MemoryOpenLoop.lifecycle_state == "open")
                elif kind == "memory_prospective_item":
                    predicate.append(MemoryProspectiveItem.lifecycle_state.in_(
                        ("dormant", "ready", "triggered")
                    ))
                statement = select(record_column).where(*predicate).limit(1)
                if kind != "memory_event":
                    statement = statement.join(
                        MemoryEvent, MemoryEvent.event_id == event_column
                    )
                if (await session.execute(statement)).scalar_one_or_none() is None:
                    return False
        return True


__all__ = ["PostgresEventSource", "PostgresEventSourceScopeError"]
