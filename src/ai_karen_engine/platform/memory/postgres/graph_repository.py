"""PostgreSQL implementation of the canonical memory graph repository.

The graph is a rebuildable projection over governed memory records. PostgreSQL
owns persistence; NeuroRecall owns final retrieval strategy/ranking.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text

from ai_karen_engine.core.memory.graph.models import EntityNode, GraphEdge
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import MemoryEntity, MemoryRelation


class PostgresGraphScopeError(ValueError):
    """Raised when graph access lacks valid tenant/user/identifier scope."""


class PostgresGraphRepository:
    """Tenant-scoped temporal graph projection stored in canonical PostgreSQL."""

    backend_name = "postgres"
    durable = True

    async def initialize(self) -> None:
        # Schema creation is migration-owned. This verifies connectivity only.
        async with async_transaction_scope() as session:
            await session.execute(text("SELECT 1"))

    async def upsert_entity(
        self,
        entity: EntityNode,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        tenant_uuid = self._uuid(tenant_id, "tenant_id")
        user_uuid = self._uuid(user_id, "user_id")
        entity_uuid = self._uuid(entity.entity_id, "entity_id")
        normalized = str(entity.normalized or entity.text).strip().casefold()
        if not normalized:
            raise PostgresGraphScopeError("entity normalized text is required")

        async with async_transaction_scope(tenant_id=tenant_id) as session:
            existing = await session.get(MemoryEntity, entity_uuid)
            if existing is None:
                session.add(
                    MemoryEntity(
                        entity_id=entity_uuid,
                        tenant_id=tenant_uuid,
                        user_id=user_uuid,
                        canonical_text=entity.text,
                        normalized_text=normalized,
                        entity_type=entity.type,
                        metadata_payload={},
                    )
                )
                return

            if existing.tenant_id != tenant_uuid or existing.user_id != user_uuid:
                raise PostgresGraphScopeError("entity_id belongs to another tenant/user scope")
            existing.canonical_text = entity.text
            existing.normalized_text = normalized
            existing.entity_type = entity.type

    async def create_edge(self, edge: GraphEdge) -> None:
        tenant_id = str(edge.tenant_id or "").strip()
        user_id = str(edge.user_id or "").strip()
        if not tenant_id or not user_id:
            raise PostgresGraphScopeError("tenant_id and user_id are required for graph edges")

        tenant_uuid = self._uuid(tenant_id, "tenant_id")
        user_uuid = self._uuid(user_id, "user_id")
        source_uuid = self._uuid(edge.from_id, "source_id")
        target_uuid = self._uuid(edge.to_id, "target_id")
        conversation_uuid = self._optional_uuid(edge.conversation_id, "conversation_id")
        metadata = dict(edge.metadata or {})
        source_event_uuid = self._optional_uuid(metadata.pop("source_event_id", None), "source_event_id")
        source_memory_uuid = self._optional_uuid(metadata.pop("source_memory_id", None), "source_memory_id")

        async with async_transaction_scope(tenant_id=tenant_id) as session:
            duplicate_stmt = select(MemoryRelation.relation_id).where(
                MemoryRelation.tenant_id == tenant_uuid,
                MemoryRelation.user_id == user_uuid,
                MemoryRelation.source_id == source_uuid,
                MemoryRelation.target_id == target_uuid,
                MemoryRelation.relation_type == edge.relationship,
                MemoryRelation.lifecycle_state == "active",
            ).limit(1)
            duplicate = (await session.execute(duplicate_stmt)).scalar_one_or_none()
            if duplicate is not None:
                return

            session.add(
                MemoryRelation(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    conversation_id=conversation_uuid,
                    source_id=source_uuid,
                    target_id=target_uuid,
                    relation_type=edge.relationship,
                    metadata_payload=metadata,
                    confidence=float(metadata.get("confidence", 1.0) or 1.0),
                    weight=float(metadata.get("weight", 1.0) or 1.0),
                    salience=float(metadata.get("salience", 0.5) or 0.5),
                    lifecycle_state=str(metadata.get("lifecycle_state", "active")),
                    source_memory_id=source_memory_uuid,
                    source_event_id=source_event_uuid,
                )
            )

    async def find_related_events(
        self,
        tenant_id: str,
        user_id: str,
        event_id: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        seed_id = self._uuid(event_id, "event_id")
        return await self._find_event_neighbors(
            tenant_id=tenant_id,
            user_id=user_id,
            seed_id=seed_id,
            max_depth=max_depth,
            limit=limit,
        )

    async def find_entity_context(
        self,
        tenant_id: str,
        user_id: str,
        entity_text: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        tenant_uuid = self._uuid(tenant_id, "tenant_id")
        user_uuid = self._uuid(user_id, "user_id")
        normalized = str(entity_text or "").strip().casefold()
        if not normalized:
            return []

        async with async_transaction_scope(tenant_id=tenant_id) as session:
            stmt = (
                select(MemoryEntity.entity_id)
                .where(
                    MemoryEntity.tenant_id == tenant_uuid,
                    MemoryEntity.user_id == user_uuid,
                    MemoryEntity.normalized_text == normalized,
                )
                .order_by(MemoryEntity.updated_at.desc())
                .limit(5)
            )
            entity_ids = list((await session.execute(stmt)).scalars().all())

        results: list[dict] = []
        for entity_id in entity_ids:
            remaining = max(0, limit - len(results))
            if remaining == 0:
                break
            results.extend(
                await self._find_event_neighbors(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    seed_id=entity_id,
                    max_depth=max_depth,
                    limit=remaining,
                )
            )
        return results[:limit]

    async def _find_event_neighbors(
        self,
        *,
        tenant_id: str,
        user_id: str,
        seed_id: uuid.UUID,
        max_depth: int,
        limit: int,
    ) -> list[dict]:
        tenant_uuid = self._uuid(tenant_id, "tenant_id")
        user_uuid = self._uuid(user_id, "user_id")
        depth = min(max(int(max_depth), 0), 8)
        result_limit = min(max(int(limit), 0), 200)
        if depth == 0 or result_limit == 0:
            return []

        query = text(
            """
            WITH RECURSIVE walk(node_id, depth, relationship, path) AS (
                SELECT
                    CASE WHEN r.source_id = :seed_id THEN r.target_id ELSE r.source_id END,
                    1,
                    r.relation_type,
                    ARRAY[
                        :seed_id::uuid,
                        CASE WHEN r.source_id = :seed_id THEN r.target_id ELSE r.source_id END
                    ]::uuid[]
                FROM memory_relation r
                WHERE r.tenant_id = :tenant_id
                  AND r.user_id = :user_id
                  AND r.lifecycle_state = 'active'
                  AND (r.valid_from IS NULL OR r.valid_from <= CURRENT_TIMESTAMP)
                  AND (r.valid_to IS NULL OR r.valid_to > CURRENT_TIMESTAMP)
                  AND (r.source_id = :seed_id OR r.target_id = :seed_id)

                UNION ALL

                SELECT
                    CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END,
                    w.depth + 1,
                    r.relation_type,
                    w.path || CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END
                FROM walk w
                JOIN memory_relation r
                  ON (r.source_id = w.node_id OR r.target_id = w.node_id)
                WHERE w.depth < :max_depth
                  AND r.tenant_id = :tenant_id
                  AND r.user_id = :user_id
                  AND r.lifecycle_state = 'active'
                  AND (r.valid_from IS NULL OR r.valid_from <= CURRENT_TIMESTAMP)
                  AND (r.valid_to IS NULL OR r.valid_to > CURRENT_TIMESTAMP)
                  AND NOT (
                      CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END
                      = ANY(w.path)
                  )
            )
            SELECT DISTINCT ON (e.event_id)
                e.event_id,
                w.relationship,
                w.depth
            FROM walk w
            JOIN memory_event e ON e.event_id = w.node_id
            WHERE e.tenant_id = :tenant_id
              AND e.user_id = :user_id
              AND e.consent_state = 'granted'
              AND (e.valid_to IS NULL OR e.valid_to > CURRENT_TIMESTAMP)
            ORDER BY e.event_id, w.depth ASC
            LIMIT :result_limit
            """
        )

        async with async_transaction_scope(tenant_id=tenant_id) as session:
            rows = (
                await session.execute(
                    query,
                    {
                        "seed_id": seed_id,
                        "tenant_id": tenant_uuid,
                        "user_id": user_uuid,
                        "max_depth": depth,
                        "result_limit": result_limit,
                    },
                )
            ).mappings().all()

        return [
            {
                "event_id": str(row["event_id"]),
                "relationship": row["relationship"],
                "depth": int(row["depth"]),
                "source": "postgres_graph",
            }
            for row in rows
        ]

    async def close(self) -> None:
        # Engine lifecycle is owned by PostgresEngine, not this repository.
        return None

    @staticmethod
    def _uuid(value: Any, field_name: str) -> uuid.UUID:
        try:
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise PostgresGraphScopeError(f"{field_name} must be a valid UUID") from exc

    @classmethod
    def _optional_uuid(cls, value: Any, field_name: str) -> uuid.UUID | None:
        if value in (None, ""):
            return None
        return cls._uuid(value, field_name)


__all__ = ["PostgresGraphRepository", "PostgresGraphScopeError"]
