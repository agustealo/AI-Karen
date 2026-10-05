"""PostgreSQL goal/prospective candidate retrieval beneath NeuroRecall."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryQuery,
    MemoryType,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import MemoryEvent, MemoryProspectiveItem, MemoryUserGoal


class PostgresUserStateRecallRetriever:
    """Return context-relevant active goals and prospective items.

    This adapter only produces tenant/user-scoped candidates. NeuroRecall remains
    the fusion, ranking, guardrail, and selection authority.
    """

    _BROAD_CUES = (
        "goal",
        "goals",
        "plan",
        "plans",
        "trying",
        "progress",
        "interview",
        "upcoming",
        "remember",
        "about me",
        "what should i",
        "what am i",
    )

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        try:
            tenant_uuid = uuid.UUID(str(query.tenant_id or ""))
            user_uuid = uuid.UUID(str(query.user_id or ""))
        except ValueError:
            return []

        query_text = str(query.text or "").strip()
        terms = self._terms(query_text)
        broad = any(cue in query_text.casefold() for cue in self._BROAD_CUES)
        if not terms and not broad:
            return []

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        top_k = min(max(int(query.top_k or 10), 1), 50)

        async with async_transaction_scope(tenant_id=str(query.tenant_id)) as session:
            goal_rows = (
                await session.execute(
                    select(MemoryUserGoal)
                    .join(MemoryEvent, MemoryEvent.event_id == MemoryUserGoal.event_id)
                    .where(
                        MemoryUserGoal.tenant_id == tenant_uuid,
                        MemoryUserGoal.user_id == user_uuid,
                        MemoryEvent.tenant_id == tenant_uuid,
                        MemoryEvent.user_id == user_uuid,
                        MemoryEvent.consent_state == "granted",
                        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
                        MemoryUserGoal.lifecycle_state.in_(
                            ("active", "blocked", "paused", "at_risk")
                        ),
                        or_(
                            MemoryUserGoal.valid_to.is_(None),
                            MemoryUserGoal.valid_to > now,
                        ),
                    )
                    .order_by(
                        MemoryUserGoal.confidence.desc(),
                        MemoryUserGoal.updated_at.desc(),
                    )
                    .limit(top_k * 2)
                )
            ).scalars().all()

            prospective_rows = (
                await session.execute(
                    select(MemoryProspectiveItem)
                    .join(
                        MemoryEvent,
                        MemoryEvent.event_id == MemoryProspectiveItem.event_id,
                    )
                    .where(
                        MemoryProspectiveItem.tenant_id == tenant_uuid,
                        MemoryProspectiveItem.user_id == user_uuid,
                        MemoryEvent.tenant_id == tenant_uuid,
                        MemoryEvent.user_id == user_uuid,
                        MemoryEvent.consent_state == "granted",
                        or_(MemoryEvent.valid_to.is_(None), MemoryEvent.valid_to > now),
                        MemoryProspectiveItem.lifecycle_state.in_(
                            ("dormant", "ready", "active", "triggered")
                        ),
                        or_(
                            MemoryProspectiveItem.valid_to.is_(None),
                            MemoryProspectiveItem.valid_to > now,
                        ),
                    )
                    .order_by(
                        MemoryProspectiveItem.target_at.asc().nullslast(),
                        MemoryProspectiveItem.confidence.desc(),
                        MemoryProspectiveItem.updated_at.desc(),
                    )
                    .limit(top_k * 2)
                )
            ).scalars().all()

        candidates: list[MemoryEntry] = []
        for row in goal_rows:
            relevance = self._relevance(
                query_text,
                f"{row.description} {row.target_text or ''}",
                broad=broad,
            )
            if relevance <= 0.0:
                continue
            candidates.append(self._goal_entry(row, query, relevance))

        for row in prospective_rows:
            relevance = self._relevance(
                query_text,
                f"{row.event_type} {row.description} {row.temporal_text or ''}",
                broad=broad,
            )
            if relevance <= 0.0:
                continue
            candidates.append(self._prospective_entry(row, query, relevance))

        candidates.sort(
            key=lambda item: (float(item.relevance or 0.0), float(item.confidence or 0.0)),
            reverse=True,
        )
        return candidates[:top_k]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[\w'-]{3,}", text.casefold(), flags=re.UNICODE)
            if token not in {"what", "when", "where", "with", "that", "this", "have", "about"}
        }

    @classmethod
    def _relevance(cls, query: str, content: str, *, broad: bool) -> float:
        query_terms = cls._terms(query)
        content_terms = cls._terms(content)
        if query_terms:
            overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
            if overlap > 0:
                return max(0.55, min(1.0, 0.55 + overlap * 0.45))
        return 0.45 if broad else 0.0

    @staticmethod
    def _goal_entry(
        row: MemoryUserGoal,
        query: MemoryQuery,
        relevance: float,
    ) -> MemoryEntry:
        created_at = row.created_at or datetime.utcnow()
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            session_id=query.session_id,
            source="postgres_user_goal",
            custom={
                "source_store": "postgres",
                "memory_class": "semantic",
                "goal_id": str(row.goal_id),
                "event_id": str(row.event_id),
                "lifecycle_state": row.lifecycle_state,
                "goal_type": row.goal_type,
                "target_at": row.target_at.isoformat() if row.target_at else None,
                "freshness": 1.0,
                "source_trust": 1.0,
                "tenant_match": 1.0,
                "provenance": {
                    "store": "postgres",
                    "record_type": "memory_user_goal",
                    "goal_id": str(row.goal_id),
                    "event_id": str(row.event_id),
                    "source_type": row.source_type,
                    "source_ref": row.source_ref,
                },
            },
        )
        return MemoryEntry(
            id=str(row.goal_id),
            content=f"Active goal: {row.description}",
            memory_type=MemoryType.SEMANTIC,
            namespace=MemoryNamespace.LONG_TERM,
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            relevance=relevance,
            confidence=float(row.confidence or 0.0),
            importance=8.0,
            metadata=metadata,
        )

    @staticmethod
    def _prospective_entry(
        row: MemoryProspectiveItem,
        query: MemoryQuery,
        relevance: float,
    ) -> MemoryEntry:
        created_at = row.created_at or datetime.utcnow()
        temporal = f" ({row.temporal_text})" if row.temporal_text else ""
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            session_id=query.session_id,
            source="postgres_prospective_memory",
            custom={
                "source_store": "postgres",
                "memory_class": "episodic",
                "prospective_id": str(row.prospective_id),
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "lifecycle_state": row.lifecycle_state,
                "target_at": row.target_at.isoformat() if row.target_at else None,
                "freshness": 1.0,
                "source_trust": 1.0,
                "tenant_match": 1.0,
                "provenance": {
                    "store": "postgres",
                    "record_type": "memory_prospective_item",
                    "prospective_id": str(row.prospective_id),
                    "event_id": str(row.event_id),
                    "source_type": row.source_type,
                    "source_ref": row.source_ref,
                },
            },
        )
        return MemoryEntry(
            id=str(row.prospective_id),
            content=f"Upcoming {row.event_type}: {row.description}{temporal}",
            memory_type=MemoryType.EPISODIC,
            namespace=MemoryNamespace.LONG_TERM,
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            relevance=relevance,
            confidence=float(row.confidence or 0.0),
            importance=8.0,
            metadata=metadata,
        )


__all__ = ["PostgresUserStateRecallRetriever"]
