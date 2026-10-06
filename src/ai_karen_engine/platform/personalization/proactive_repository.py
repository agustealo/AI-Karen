"""PostgreSQL evidence adapter for proactive continuity intelligence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text

from ai_karen_engine.core.intelligence.proactive.contracts import (
    ContinuityEvidence,
    ProactiveContinuityRepository,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


class PostgresProactiveContinuityRepository(ProactiveContinuityRepository):
    """Read current continuity evidence without owning user-state persistence."""

    @staticmethod
    def _scope(tenant_id: str, user_id: str) -> tuple[str, str]:
        tenant = str(tenant_id or "").strip()
        user = str(user_id or "").strip()
        if not tenant or tenant == "default":
            raise ValueError("proactive continuity requires explicit tenant_id")
        if not user:
            raise ValueError("proactive continuity requires explicit user_id")
        uuid.UUID(tenant)
        uuid.UUID(user)
        return tenant, user

    async def load_evidence(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[ContinuityEvidence]:
        tenant, user = self._scope(tenant_id, user_id)
        bounded = max(1, min(int(limit), 500))
        now = datetime.utcnow()

        async with async_transaction_scope(tenant_id=tenant) as session:
            goals = (
                await session.execute(
                    text(
                        """
                        SELECT
                            g.goal_id AS source_id,
                            g.description AS subject,
                            g.lifecycle_state AS state,
                            g.confidence,
                            g.target_at,
                            g.goal_type,
                            g.metadata_payload
                        FROM public.memory_user_goal g
                        JOIN public.memory_event me ON me.event_id = g.event_id
                        WHERE g.tenant_id = CAST(:tenant_id AS uuid)
                          AND g.user_id = CAST(:user_id AS uuid)
                          AND g.lifecycle_state IN (
                              'active', 'blocked', 'paused', 'at_risk', 'satisfied'
                          )
                          AND (g.valid_to IS NULL OR g.valid_to > :now)
                          AND me.consent_state = 'granted'
                          AND (me.valid_to IS NULL OR me.valid_to > :now)
                        ORDER BY g.updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "now": now,
                        "limit": bounded,
                    },
                )
            ).mappings().all()

            open_loops = (
                await session.execute(
                    text(
                        """
                        SELECT
                            o.open_loop_id AS source_id,
                            o.description AS subject,
                            o.lifecycle_state AS state,
                            o.confidence,
                            o.target_at,
                            o.domain,
                            o.loop_type,
                            o.metadata_payload
                        FROM public.memory_open_loop o
                        JOIN public.memory_event me ON me.event_id = o.event_id
                        WHERE o.tenant_id = CAST(:tenant_id AS uuid)
                          AND o.user_id = CAST(:user_id AS uuid)
                          AND o.lifecycle_state = 'open'
                          AND (o.valid_to IS NULL OR o.valid_to > :now)
                          AND me.consent_state = 'granted'
                          AND (me.valid_to IS NULL OR me.valid_to > :now)
                        ORDER BY o.target_at ASC NULLS LAST, o.updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "now": now,
                        "limit": bounded,
                    },
                )
            ).mappings().all()

            prospective = (
                await session.execute(
                    text(
                        """
                        SELECT
                            p.prospective_id AS source_id,
                            p.description AS subject,
                            p.lifecycle_state AS state,
                            p.confidence,
                            p.target_at,
                            p.event_type,
                            p.metadata_payload
                        FROM public.memory_prospective_item p
                        JOIN public.memory_event me ON me.event_id = p.event_id
                        WHERE p.tenant_id = CAST(:tenant_id AS uuid)
                          AND p.user_id = CAST(:user_id AS uuid)
                          AND p.lifecycle_state IN ('dormant', 'ready', 'triggered')
                          AND (p.valid_to IS NULL OR p.valid_to > :now)
                          AND me.consent_state = 'granted'
                          AND (me.valid_to IS NULL OR me.valid_to > :now)
                        ORDER BY p.target_at ASC NULLS LAST, p.updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "now": now,
                        "limit": bounded,
                    },
                )
            ).mappings().all()

            behaviors = (
                await session.execute(
                    text(
                        """
                        SELECT
                            pattern_id AS source_id,
                            pattern_type,
                            context_signature,
                            observation_count,
                            confidence,
                            recurrence,
                            metadata_payload
                        FROM public.personalization_behavior_pattern
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND user_id = CAST(:user_id AS uuid)
                          AND observation_count >= 3
                          AND confidence >= 0.6
                        ORDER BY confidence DESC, last_seen DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "limit": bounded,
                    },
                )
            ).mappings().all()

        evidence: list[ContinuityEvidence] = []
        evidence.extend(
            ContinuityEvidence(
                source_type="goal",
                source_id=str(row["source_id"]),
                subject=str(row["subject"]),
                state=str(row["state"]),
                confidence=float(row["confidence"] or 0.0),
                target_at=row["target_at"],
                domain=self._metadata(row["metadata_payload"]).get("domain"),
                metadata={
                    "goal_type": row["goal_type"],
                    **self._metadata(row["metadata_payload"]),
                },
            )
            for row in goals
        )
        evidence.extend(
            ContinuityEvidence(
                source_type="open_loop",
                source_id=str(row["source_id"]),
                subject=str(row["subject"]),
                state=str(row["state"]),
                confidence=float(row["confidence"] or 0.0),
                target_at=row["target_at"],
                domain=row["domain"],
                metadata={
                    "loop_type": row["loop_type"],
                    **self._metadata(row["metadata_payload"]),
                },
            )
            for row in open_loops
        )
        evidence.extend(
            ContinuityEvidence(
                source_type="prospective",
                source_id=str(row["source_id"]),
                subject=str(row["subject"]),
                state=str(row["state"]),
                confidence=float(row["confidence"] or 0.0),
                target_at=row["target_at"],
                domain=self._metadata(row["metadata_payload"]).get("domain"),
                metadata={
                    "event_type": row["event_type"],
                    **self._metadata(row["metadata_payload"]),
                },
            )
            for row in prospective
        )
        evidence.extend(
            ContinuityEvidence(
                source_type="behavior",
                source_id=str(row["source_id"]),
                subject=str(row["pattern_type"]),
                state=str(row["recurrence"]),
                confidence=float(row["confidence"] or 0.0),
                domain=self._metadata(row["metadata_payload"]).get("domain"),
                observation_count=int(row["observation_count"] or 0),
                metadata={
                    "context_signature": row["context_signature"],
                    **self._metadata(row["metadata_payload"]),
                },
            )
            for row in behaviors
        )
        return evidence

    @staticmethod
    def _metadata(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}


__all__ = ["PostgresProactiveContinuityRepository"]
