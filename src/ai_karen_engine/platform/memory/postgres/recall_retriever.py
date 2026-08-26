"""Canonical PostgreSQL durable-memory recall adapter.

This module is a platform adapter. It owns PostgreSQL-specific query execution,
not recall strategy. NeuroRecall remains the memory-domain recall authority.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import or_, select

from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryQuery,
    MemoryType,
)

from .ledger_models import MemoryAssertion


class PostgresRecallScopeError(ValueError):
    """Raised when durable recall lacks mandatory tenant/user scope."""


class PostgresRecallRetriever:
    """Async, tenant-scoped retrieval from the canonical memory assertion ledger."""

    def __init__(self, session_factory: Callable[..., Any] | None = None) -> None:
        self._session_factory = session_factory

    def _resolve_session_factory(self) -> Callable[..., Any]:
        if self._session_factory is not None:
            return self._session_factory

        from ai_karen_engine.database.client import db_client

        factory = getattr(db_client, "get_async_session", None)
        if factory is None:
            raise RuntimeError("PostgreSQL async session factory is unavailable")
        self._session_factory = factory
        return factory

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Retrieve durable memories for exactly one tenant/user scope."""
        tenant_id = str(query.tenant_id or "").strip()
        user_id = str(query.user_id or "").strip()
        if not tenant_id:
            raise PostgresRecallScopeError("tenant_id is required for durable memory recall")
        if not user_id:
            raise PostgresRecallScopeError("user_id is required for durable memory recall")

        try:
            tenant_uuid = uuid.UUID(tenant_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError as exc:
            raise PostgresRecallScopeError("tenant_id and user_id must be valid UUIDs") from exc

        top_k = min(max(int(query.top_k or 10), 1), 100)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        stmt = (
            select(MemoryAssertion)
            .where(
                MemoryAssertion.tenant_id == tenant_uuid,
                MemoryAssertion.user_id == user_uuid,
                MemoryAssertion.consent_state == "granted",
                or_(MemoryAssertion.valid_to.is_(None), MemoryAssertion.valid_to > now),
            )
            .order_by(MemoryAssertion.confidence.desc(), MemoryAssertion.created_at.desc())
            .limit(top_k)
        )

        text = str(query.text or "").strip()
        if text:
            stmt = stmt.where(MemoryAssertion.content.contains(text, autoescape=True))

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._to_entry(row, query, text) for row in rows]

    @staticmethod
    def _to_entry(row: MemoryAssertion, query: MemoryQuery, query_text: str) -> MemoryEntry:
        content = str(row.content or "")
        relevance = PostgresRecallRetriever._lexical_relevance(query_text, content)
        created_at = row.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            source="postgres_memory_ledger",
            custom={
                "source_store": "postgres",
                "assertion_id": str(row.assertion_id),
                "event_id": str(row.event_id),
                "scope": row.scope,
                "consent_state": row.consent_state,
                "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "provenance": {
                    "store": "postgres",
                    "record_type": "memory_assertion",
                    "assertion_id": str(row.assertion_id),
                    "event_id": str(row.event_id),
                },
            },
        )
        return MemoryEntry(
            id=str(row.assertion_id),
            content=content,
            memory_type=MemoryType.SEMANTIC,
            namespace=MemoryNamespace.LONG_TERM,
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            relevance=relevance,
            confidence=float(row.confidence or 0.0),
            importance=max(1.0, min(10.0, 1.0 + float(row.confidence or 0.0) * 9.0)),
            metadata=metadata,
        )

    @staticmethod
    def _lexical_relevance(query_text: str, content: str) -> float:
        query_terms = {term for term in query_text.casefold().split() if term}
        if not query_terms:
            return 0.5
        content_terms = set(content.casefold().split())
        overlap = len(query_terms & content_terms) / len(query_terms)
        return max(0.1, min(1.0, overlap))


__all__ = ["PostgresRecallRetriever", "PostgresRecallScopeError"]
