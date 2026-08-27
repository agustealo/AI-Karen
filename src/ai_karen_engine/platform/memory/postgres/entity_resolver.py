"""PostgreSQL entity resolution for canonical memory graph identities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import desc, func, or_, select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .entity_models import MemoryEntityAlias
from .ledger_models import MemoryEntity


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    entity_id: str
    canonical_text: str
    matched_text: str
    match_type: str
    score: float


class PostgresEntityResolver:
    """Resolve raw entity cues against canonical entities and aliases."""

    def __init__(self, *, fuzzy_threshold: float = 0.55) -> None:
        self.fuzzy_threshold = max(0.0, min(1.0, float(fuzzy_threshold)))

    async def resolve_cues(
        self,
        *,
        tenant_id: str,
        user_id: str,
        cues: Iterable[str],
        limit: int = 8,
    ) -> list[ResolvedEntity]:
        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return []

        bounded_limit = min(max(int(limit), 1), 20)
        resolved: dict[str, ResolvedEntity] = {}

        async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
            for raw_cue in cues:
                cue = " ".join(str(raw_cue or "").split()).casefold()
                if not cue:
                    continue

                entity_similarity = func.similarity(MemoryEntity.normalized_text, cue)
                entity_stmt = (
                    select(MemoryEntity, entity_similarity.label("score"))
                    .where(
                        MemoryEntity.tenant_id == tenant_uuid,
                        MemoryEntity.user_id == user_uuid,
                        or_(
                            MemoryEntity.normalized_text == cue,
                            entity_similarity >= self.fuzzy_threshold,
                        ),
                    )
                    .order_by(
                        desc(MemoryEntity.normalized_text == cue),
                        desc(entity_similarity),
                        MemoryEntity.updated_at.desc(),
                    )
                    .limit(5)
                )
                for entity, score in (await session.execute(entity_stmt)).all():
                    exact = entity.normalized_text == cue
                    item = ResolvedEntity(
                        entity_id=str(entity.entity_id),
                        canonical_text=str(entity.canonical_text),
                        matched_text=str(raw_cue),
                        match_type="exact" if exact else "fuzzy",
                        score=1.0 if exact else float(score or 0.0),
                    )
                    current = resolved.get(item.entity_id)
                    if current is None or item.score > current.score:
                        resolved[item.entity_id] = item

                alias_similarity = func.similarity(MemoryEntityAlias.normalized_alias, cue)
                alias_stmt = (
                    select(MemoryEntityAlias, MemoryEntity, alias_similarity.label("score"))
                    .join(MemoryEntity, MemoryEntity.entity_id == MemoryEntityAlias.entity_id)
                    .where(
                        MemoryEntityAlias.tenant_id == tenant_uuid,
                        MemoryEntityAlias.user_id == user_uuid,
                        MemoryEntity.tenant_id == tenant_uuid,
                        MemoryEntity.user_id == user_uuid,
                        or_(
                            MemoryEntityAlias.normalized_alias == cue,
                            alias_similarity >= self.fuzzy_threshold,
                        ),
                    )
                    .order_by(
                        desc(MemoryEntityAlias.normalized_alias == cue),
                        desc(alias_similarity),
                        MemoryEntityAlias.confidence.desc(),
                    )
                    .limit(5)
                )
                for alias, entity, score in (await session.execute(alias_stmt)).all():
                    exact = alias.normalized_alias == cue
                    combined = (1.0 if exact else float(score or 0.0)) * float(alias.confidence or 0.0)
                    item = ResolvedEntity(
                        entity_id=str(entity.entity_id),
                        canonical_text=str(entity.canonical_text),
                        matched_text=str(raw_cue),
                        match_type="alias_exact" if exact else "alias_fuzzy",
                        score=combined,
                    )
                    current = resolved.get(item.entity_id)
                    if current is None or item.score > current.score:
                        resolved[item.entity_id] = item

                if len(resolved) >= bounded_limit * 2:
                    break

        return sorted(
            resolved.values(),
            key=lambda item: (item.score, len(item.canonical_text)),
            reverse=True,
        )[:bounded_limit]


__all__ = ["PostgresEntityResolver", "ResolvedEntity"]
