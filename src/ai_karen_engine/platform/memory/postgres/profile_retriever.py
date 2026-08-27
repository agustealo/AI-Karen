"""PostgreSQL profile-fact candidate retrieval for NeuroRecall."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from ai_karen_engine.core.memory.neuro import decide_activation_mode
from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryQuery,
    MemoryType,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import ProfileFact


class PostgresProfileRecallRetriever:
    """Return current profile facts as scoped NeuroRecall candidates."""

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        activation = decide_activation_mode(query=query.text or "", has_profile=True)
        if activation.mode.value not in {"profile", "deep"} and not self._looks_like_profile_query(query.text or ""):
            return []

        try:
            tenant_uuid = uuid.UUID(str(query.tenant_id or ""))
            user_uuid = uuid.UUID(str(query.user_id or ""))
        except ValueError:
            return []

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        top_k = min(max(int(query.top_k or 10), 1), 50)
        async with async_transaction_scope(tenant_id=str(query.tenant_id)) as session:
            stmt = (
                select(ProfileFact)
                .where(
                    ProfileFact.tenant_id == tenant_uuid,
                    ProfileFact.user_id == user_uuid,
                    or_(ProfileFact.valid_to.is_(None), ProfileFact.valid_to > now),
                )
                .order_by(ProfileFact.confidence.desc(), ProfileFact.updated_at.desc())
                .limit(top_k)
            )
            rows = (await session.execute(stmt)).scalars().all()

        return [self._entry(row, query) for row in rows]

    @staticmethod
    def _looks_like_profile_query(text: str) -> bool:
        q = text.casefold()
        cues = (
            "about me",
            "my preference",
            "my preferences",
            "favorite",
            "my birthday",
            "what do you know about me",
            "how do i like",
            "my style",
        )
        return any(cue in q for cue in cues)

    @staticmethod
    def _entry(row: ProfileFact, query: MemoryQuery) -> MemoryEntry:
        value = row.value
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        content = f"{row.attribute}: {rendered}"
        created_at = row.created_at or datetime.utcnow()
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            session_id=getattr(query, "session_id", None),
            source="postgres_profile_fact",
            custom={
                "source_store": "postgres",
                "memory_class": "semantic",
                "profile_fact_id": str(row.fact_id),
                "event_id": str(row.event_id),
                "category": row.category,
                "attribute": row.attribute,
                "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "semantic_similarity": 0.55,
                "lexical_match": 0.35,
                "freshness": 1.0,
                "source_trust": 1.0,
                "tenant_match": 1.0,
                "provenance": {
                    "store": "postgres",
                    "record_type": "profile_fact",
                    "fact_id": str(row.fact_id),
                    "event_id": str(row.event_id),
                    "source_type": row.source_type,
                    "source_ref": row.source_ref,
                },
            },
        )
        return MemoryEntry(
            id=str(row.fact_id),
            content=content,
            memory_type=MemoryType.SEMANTIC,
            namespace=MemoryNamespace.LONG_TERM,
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            relevance=0.55,
            confidence=float(row.confidence or 0.0),
            importance=7.0,
            metadata=metadata,
        )


__all__ = ["PostgresProfileRecallRetriever"]
