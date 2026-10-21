"""Canonical PostgreSQL durable-memory recall adapter.

This module owns PostgreSQL-specific durable candidate retrieval. NeuroRecall
remains the memory-domain recall authority.
"""

from __future__ import annotations

import re
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
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .consent_filter import recallable_memory_event
from .ledger_models import MemoryAssertion, MemoryEvent


class PostgresRecallScopeError(ValueError):
    """Raised when durable recall lacks mandatory tenant/user scope."""


class PostgresRecallRetriever:
    """Async, tenant-scoped retrieval from the canonical memory assertion ledger."""

    def __init__(self, session_factory: Callable[..., Any] | None = None) -> None:
        # Injection is retained for unit/integration tests. Production recall uses
        # async_transaction_scope so the Supabase/Postgres RLS tenant setting is
        # applied consistently with the canonical persistence contract.
        self._session_factory = session_factory

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
            select(MemoryAssertion, MemoryEvent.payload)
            .join(MemoryEvent, MemoryEvent.event_id == MemoryAssertion.event_id)
            .where(
                MemoryAssertion.tenant_id == tenant_uuid,
                MemoryAssertion.user_id == user_uuid,
                MemoryAssertion.consent_state == "granted",
                or_(MemoryAssertion.valid_from.is_(None), MemoryAssertion.valid_from <= now),
                or_(MemoryAssertion.valid_to.is_(None), MemoryAssertion.valid_to > now),
                recallable_memory_event(
                    tenant_id=tenant_uuid, user_id=user_uuid, now=now,
                ),
            )
        )

        text = str(query.text or "").strip()
        terms = self._query_terms(text)
        if terms:
            stmt = stmt.where(
                or_(*(MemoryAssertion.content.contains(term, autoescape=True) for term in terms))
            )

        stmt = stmt.order_by(
            MemoryAssertion.confidence.desc(),
            MemoryAssertion.created_at.desc(),
        ).limit(top_k)

        if self._session_factory is not None:
            async with self._session_factory() as session:
                result = await session.execute(stmt)
                rows = result.all()
        else:
            async with async_transaction_scope(tenant_id=tenant_id) as session:
                result = await session.execute(stmt)
                rows = result.all()

        return [self._to_entry(row, query, text, payload) for row, payload in rows]

    @staticmethod
    def _query_terms(text: str) -> tuple[str, ...]:
        if not text:
            return ()
        terms: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[\w'-]{2,}", text.casefold(), flags=re.UNICODE):
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= 8:
                break
        return tuple(terms)

    @staticmethod
    def _to_entry(\n        row: MemoryAssertion, query: MemoryQuery, query_text: str,\n        event_payload: dict[str, Any] | None = None,\n    ) -> MemoryEntry:
        content = str(row.content or "")
        relevance = PostgresRecallRetriever._lexical_relevance(query_text, content)
        created_at = row.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
        # The governed ledger event owns the original entry provenance.
        # Recover only persona attribution; never reuse stored identity,
        # consent or authorization metadata in place of assertion checks.
        if not isinstance(event_payload, dict):
            event_payload = {}
        saved_metadata = event_payload.get("metadata")
        if not isinstance(saved_metadata, dict):
            saved_metadata = {}
        saved_custom = saved_metadata.get("custom")
        if not isinstance(saved_custom, dict):
            saved_custom = {}
        persona_id = saved_custom.get("persona_id")
        persona_provenance = (
            {"persona_id": persona_id}
            if isinstance(persona_id, str) and persona_id.strip()
            else {}
        )
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            source="postgres_memory_ledger",
            custom={
                "source_store": "postgres",
                **persona_provenance,
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
        query_terms = set(PostgresRecallRetriever._query_terms(query_text))
        if not query_terms:
            return 0.5
        content_terms = set(PostgresRecallRetriever._query_terms(content))
        overlap = len(query_terms & content_terms) / len(query_terms)
        return max(0.1, min(1.0, overlap))


__all__ = ["PostgresRecallRetriever", "PostgresRecallScopeError"]
