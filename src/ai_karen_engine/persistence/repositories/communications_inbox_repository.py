"""Principal-scoped durable communications lifecycle, not execution authority."""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.core.realtime.inbox_invalidation import publish_inbox_invalidation
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

_MAX_PAGE_SIZE = 100
_MAX_REVISION = 9223372036854775806


class InboxConflict(RuntimeError):
    """An unapplied operation has a stale or impossible revision."""


class InboxNotFound(LookupError):
    """The entry and eligible source cannot be established in scope."""


class InboxOperation(str, Enum):
    READ = "read"
    ACKNOWLEDGE = "acknowledge"
    ARCHIVE = "archive"


class InboxFilter(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class InboxEntry:
    entry_id: str
    conversation_id: str
    execution_id: str
    source_kind: str
    source_status: str
    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None
    archived_at: datetime | None
    revision: int


@dataclass(frozen=True, slots=True)
class InboxCursor:
    created_at: datetime
    entry_id: str


@dataclass(frozen=True, slots=True)
class InboxPage:
    entries: tuple[InboxEntry, ...]
    next_cursor: InboxCursor | None
    active_unread_count: int


@dataclass(frozen=True, slots=True)
class InboxMutation:
    entry: InboxEntry
    changed: bool


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Canonical UUID required")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Canonical UUID required") from exc
    if normalized != value:
        raise ValueError("Canonical UUID required")
    return normalized


def _scope(tenant_id: str, user_id: str) -> dict[str, Any]:
    return {"tenant_id": _uuid(tenant_id), "user_id": _uuid(user_id)}


def _entry(row: Mapping[str, Any]) -> InboxEntry:
    return InboxEntry(
        entry_id=str(row["entry_id"]),
        conversation_id=str(row["conversation_id"]),
        execution_id=str(row["execution_id"]),
        source_kind=row["source_kind"],
        source_status=row["source_status"],
        created_at=row["created_at"],
        read_at=row["read_at"],
        acknowledged_at=row["acknowledged_at"],
        archived_at=row["archived_at"],
        revision=row["revision"],
    )


_METADATA_COLUMNS = """
    e.entry_id, e.conversation_id, e.execution_id, e.source_kind,
    e.created_at, e.read_at, e.acknowledged_at, e.archived_at, e.revision
"""
_COLUMNS = _METADATA_COLUMNS + ", r.status AS source_status"
_OWNED_CONVERSATION = """
    FROM public.communications_inbox_entries e
    JOIN public.conversations c
      ON (c.conversation_id, c.tenant_id, c.user_id) =
         (e.conversation_id, e.tenant_id, e.user_id)
"""
_SOURCE = _OWNED_CONVERSATION + """
    JOIN public.runtime_chat_runs r
      ON (r.execution_id, r.tenant_id, r.user_id, r.conversation_id) =
         (e.execution_id, e.tenant_id, e.user_id, e.conversation_id)
"""
_SCOPE = """
    e.tenant_id = CAST(:tenant_id AS uuid)
    AND e.user_id = CAST(:user_id AS uuid)
"""
_ELIGIBLE = _SCOPE + """
    AND e.source_kind = 'terminal_chat_attention'
    AND r.status IN ('failed', 'orphaned')
    AND r.terminal_at IS NOT NULL
"""
_FILTERS = {
    InboxFilter.ACTIVE: " AND e.archived_at IS NULL",
    InboxFilter.ARCHIVED: " AND e.archived_at IS NOT NULL",
    InboxFilter.ALL: "",
}
_OPERATION_COLUMNS = {
    InboxOperation.READ: "read_at",
    InboxOperation.ACKNOWLEDGE: "acknowledged_at",
    InboxOperation.ARCHIVE: "archived_at",
}


class CommunicationsInboxRepository:
    """Callers must establish authenticated principal authority before use."""

    async def list_entries(
        self, *, tenant_id: str, user_id: str, limit: int = 50,
        inbox_filter: InboxFilter = InboxFilter.ACTIVE,
        cursor: InboxCursor | None = None,
    ) -> InboxPage:
        params = _scope(tenant_id, user_id)
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError("Invalid inbox page size")
        if not isinstance(inbox_filter, InboxFilter):
            raise ValueError("Invalid inbox filter")
        predicate = _ELIGIBLE + _FILTERS[inbox_filter]
        if cursor is not None:
            if (
                not isinstance(cursor, InboxCursor)
                or not isinstance(cursor.created_at, datetime)
                or cursor.created_at.utcoffset() is None
            ):
                raise ValueError("Invalid inbox cursor")
            params.update(cursor_at=cursor.created_at, cursor_id=_uuid(cursor.entry_id))
            predicate += """
                AND (e.created_at, e.entry_id) <
                    (:cursor_at, CAST(:cursor_id AS uuid))
            """
        params["limit"] = limit + 1
        async with async_transaction_scope(
            params["tenant_id"], user_id=params["user_id"], read_only_snapshot=True
        ) as session:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} {_SOURCE} WHERE {predicate} "
                    "ORDER BY e.created_at DESC, e.entry_id DESC LIMIT :limit"
                ), params,
            )
            entries = tuple(_entry(row) for row in result.mappings().all())
            count = await session.execute(
                text(
                    f"SELECT count(*) {_SOURCE} WHERE {_ELIGIBLE} "
                    "AND e.archived_at IS NULL AND e.read_at IS NULL"
                ), params,
            )
            unread = int(count.scalar_one())
        next_cursor = None
        if len(entries) > limit:
            entries = entries[:limit]
            next_cursor = InboxCursor(entries[-1].created_at, entries[-1].entry_id)
        return InboxPage(entries, next_cursor, unread)

    @staticmethod
    async def _admit_pending(
        session: AsyncSession, params: dict[str, Any], *,
        execution_id: str | None = None, conversation_id: str | None = None,
        limit: int = 50,
    ) -> int:
        """Single bounded insertion path for exact and recovery admission."""
        filters = ""
        params = {**params, "limit": limit}
        if execution_id is not None:
            params["execution_id"] = _uuid(execution_id)
            filters += " AND r.execution_id = CAST(:execution_id AS uuid)"
        if conversation_id is not None:
            params["conversation_id"] = _uuid(conversation_id)
            filters += " AND r.conversation_id = CAST(:conversation_id AS uuid)"
        result = await session.execute(text(f"""
            WITH pending AS (
                SELECT r.tenant_id, r.user_id, r.conversation_id, r.execution_id
                FROM public.runtime_chat_runs r
                JOIN public.conversations c
                  ON (c.conversation_id, c.tenant_id, c.user_id) =
                     (r.conversation_id, r.tenant_id, r.user_id)
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.user_id = CAST(:user_id AS uuid)
                  AND r.status IN ('failed', 'orphaned')
                  AND r.terminal_at IS NOT NULL
                  AND r.communications_attention_eligible_at = r.terminal_at
                  AND r.communications_attention_conversation_id = r.conversation_id
                  AND NOT EXISTS (
                      SELECT 1 FROM public.communications_inbox_entries e
                      WHERE e.tenant_id = r.tenant_id AND e.user_id = r.user_id
                        AND e.execution_id = r.execution_id
                        AND e.source_kind = 'terminal_chat_attention'
                  )
                  {filters}
                ORDER BY r.communications_attention_eligible_at, r.execution_id
                LIMIT :limit
                FOR KEY SHARE OF c, r SKIP LOCKED
            )
            INSERT INTO public.communications_inbox_entries
                (tenant_id, user_id, conversation_id, execution_id)
            SELECT tenant_id, user_id, conversation_id, execution_id FROM pending
            ON CONFLICT (tenant_id, user_id, execution_id, source_kind)
                DO NOTHING
            RETURNING entry_id
        """), params)
        return len(result.scalars().all())

    async def reconcile_pending(
        self, *, tenant_id: str, user_id: str,
        conversation_id: str | None = None, limit: int = 50,
    ) -> int:
        """Recover committed markers without historical admission or delivery claims."""
        params = _scope(tenant_id, user_id)
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError("Invalid communications reconciliation batch size")
        async with async_transaction_scope(
            params["tenant_id"], user_id=params["user_id"]
        ) as session:
            count = await self._admit_pending(
                session, params, conversation_id=conversation_id, limit=limit,
            )
        if count:
            await publish_inbox_invalidation(tenant_id=tenant_id, user_id=user_id)
        return count

    async def admit_terminal_execution(
        self, *, tenant_id: str, user_id: str, execution_id: str,
    ) -> InboxEntry:
        """Internal admission seam; not an API or an execution retry."""
        params = _scope(tenant_id, user_id)
        params["execution_id"] = _uuid(execution_id)
        async with async_transaction_scope(
            params["tenant_id"], user_id=params["user_id"]
        ) as session:
            count = await self._admit_pending(session, params, execution_id=execution_id, limit=1)
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} {_SOURCE} WHERE {_ELIGIBLE} "
                    "AND e.execution_id = CAST(:execution_id AS uuid)"
                ), params,
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise InboxNotFound("communications_source_not_found")
            entry = _entry(row)
        if count:
            await publish_inbox_invalidation(tenant_id=tenant_id, user_id=user_id)
        return entry

    async def mutate(
        self, *, tenant_id: str, user_id: str, entry_id: str,
        operation: InboxOperation, expected_revision: int,
    ) -> InboxMutation:
        params = _scope(tenant_id, user_id)
        params["entry_id"] = _uuid(entry_id)
        if not isinstance(operation, InboxOperation):
            raise ValueError("Invalid inbox operation")
        if type(expected_revision) is not int or not 1 <= expected_revision <= _MAX_REVISION:
            raise ValueError("Invalid inbox revision")
        column = _OPERATION_COLUMNS[operation]
        predicate = _ELIGIBLE + " AND e.entry_id = CAST(:entry_id AS uuid)"
        async with async_transaction_scope(
            params["tenant_id"], user_id=params["user_id"]
        ) as session:
            result = await session.execute(
                text(f"SELECT {_COLUMNS} {_SOURCE} WHERE {predicate} FOR UPDATE OF e"),
                params,
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise InboxNotFound("communications_entry_not_found")
            current = _entry(row)
            if expected_revision > current.revision:
                raise InboxConflict("communications_revision_conflict")
            if getattr(current, column) is not None:
                # Observed durable state, not proof of which request changed it.
                return InboxMutation(current, False)
            if expected_revision != current.revision or current.revision >= _MAX_REVISION:
                raise InboxConflict("communications_revision_conflict")
            params["revision"] = expected_revision
            changed = await session.execute(text(f"""
                UPDATE public.communications_inbox_entries e
                SET {column} = clock_timestamp(), revision = revision + 1
                WHERE {_SCOPE}
                  AND e.entry_id = CAST(:entry_id AS uuid)
                  AND e.revision = :revision
                  AND e.{column} IS NULL
                RETURNING e.entry_id
            """), params)
            if changed.scalar_one_or_none() is None:
                raise InboxConflict("communications_revision_conflict")
            result = await session.execute(
                text(f"SELECT {_COLUMNS} {_SOURCE} WHERE {predicate}"), params,
            )
            updated = result.mappings().one_or_none()
            if updated is None:
                raise InboxNotFound("communications_entry_not_found")
            receipt = InboxMutation(_entry(updated), True)
        await publish_inbox_invalidation(tenant_id=tenant_id, user_id=user_id)
        return receipt

    @staticmethod
    async def export_owned_metadata(
        session: AsyncSession, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, Any]]:
        """Retained lifecycle metadata for the existing scoped privacy export."""
        params = _scope(tenant_id, user_id)
        result = await session.execute(
            text(
                f"SELECT {_METADATA_COLUMNS} {_OWNED_CONVERSATION} WHERE {_SCOPE} "
                "ORDER BY e.created_at, e.entry_id"
            ), params,
        )
        return [dict(row) for row in result.mappings().all()]
