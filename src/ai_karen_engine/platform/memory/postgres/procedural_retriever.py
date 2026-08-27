"""PostgreSQL procedural-memory candidate retrieval for NeuroRecall."""

from __future__ import annotations

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

from .procedural_models import MemoryProcedure


class PostgresProceduralRecallRetriever:
    """Return matching current procedures as scoped NeuroRecall candidates."""

    async def recall(self, query: MemoryQuery) -> list[MemoryEntry]:
        activation = decide_activation_mode(query=query.text or "")
        if activation.mode.value not in {"procedural", "deep"} and not self._looks_procedural(query.text or ""):
            return []

        try:
            tenant_uuid = uuid.UUID(str(query.tenant_id or ""))
            user_uuid = uuid.UUID(str(query.user_id or ""))
        except ValueError:
            return []

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with async_transaction_scope(tenant_id=str(query.tenant_id)) as session:
            stmt = (
                select(MemoryProcedure)
                .where(
                    MemoryProcedure.tenant_id == tenant_uuid,
                    MemoryProcedure.user_id == user_uuid,
                    MemoryProcedure.lifecycle_state == "active",
                    or_(MemoryProcedure.valid_to.is_(None), MemoryProcedure.valid_to > now),
                )
                .order_by(
                    MemoryProcedure.confidence.desc(),
                    MemoryProcedure.success_count.desc(),
                    MemoryProcedure.updated_at.desc(),
                )
                .limit(50)
            )
            rows = (await session.execute(stmt)).scalars().all()

        query_text = str(query.text or "").casefold()
        matched = [row for row in rows if self._matches(row, query_text)]
        return [self._entry(row, query) for row in matched[: min(max(query.top_k, 1), 20)]]

    @staticmethod
    def _looks_procedural(text: str) -> bool:
        q = text.casefold()
        cues = (
            "same workflow",
            "how did we",
            "what did we do",
            "procedure",
            "workflow",
            "last time",
            "do this again",
            "worked before",
            "failed before",
            "same steps",
        )
        return any(cue in q for cue in cues)

    @staticmethod
    def _matches(row: MemoryProcedure, query_text: str) -> bool:
        patterns = row.trigger_patterns if isinstance(row.trigger_patterns, list) else []
        if not patterns:
            return row.name.casefold() in query_text
        return any(str(pattern).casefold() in query_text for pattern in patterns if str(pattern).strip())

    @staticmethod
    def _entry(row: MemoryProcedure, query: MemoryQuery) -> MemoryEntry:
        sequence = row.tool_sequence if isinstance(row.tool_sequence, list) else []
        steps = " -> ".join(str(step) for step in sequence)
        content = row.name if not steps else f"{row.name}: {steps}"
        attempts = int(row.success_count or 0) + int(row.failure_count or 0)
        success_rate = (float(row.success_count or 0) / attempts) if attempts else 0.0
        created_at = row.created_at or datetime.utcnow()
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            conversation_id=query.conversation_id,
            session_id=getattr(query, "session_id", None),
            source="postgres_procedure",
            custom={
                "source_store": "postgres",
                "memory_class": "procedural",
                "procedure_id": str(row.procedure_id),
                "source_event_id": str(row.source_event_id),
                "trigger_patterns": row.trigger_patterns,
                "tool_sequence": row.tool_sequence,
                "success_count": int(row.success_count or 0),
                "failure_count": int(row.failure_count or 0),
                "procedure_success_rate": success_rate,
                "semantic_similarity": 0.6,
                "lexical_match": 0.5,
                "freshness": 1.0,
                "source_trust": 1.0,
                "tenant_match": 1.0,
                "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "provenance": {
                    "store": "postgres",
                    "record_type": "memory_procedure",
                    "procedure_id": str(row.procedure_id),
                    "source_event_id": str(row.source_event_id),
                },
            },
        )
        return MemoryEntry(
            id=str(row.procedure_id),
            content=content,
            memory_type=MemoryType.PROCEDURAL,
            namespace=MemoryNamespace.LONG_TERM,
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            relevance=0.6,
            confidence=float(row.confidence or 0.0),
            importance=8.0,
            metadata=metadata,
        )


__all__ = ["PostgresProceduralRecallRetriever"]
