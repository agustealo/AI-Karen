"""Durable personalization read/learning repository.

User identity, preferences, goals, commitments, and open loops remain owned by
canonical Memory/NeuroVault projections. This repository only reads those
projections and persists recurring behavior-learning evidence. It is not a
second user-memory authority.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from ai_karen_engine.core.personalization.contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    PreferenceCategory,
    PreferenceRecord,
    PreferenceScope,
    PreferenceStability,
    PreferenceState,
    UserGoal,
    UserGoalStatus,
    UserModelHealth,
    UserModelHealthStatus,
    make_pattern_id,
)
from ai_karen_engine.core.personalization.persistence.repository import (
    PersonalizationRepository,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


class PostgresPersonalizationRepository(PersonalizationRepository):
    """PostgreSQL-backed derived personalization repository."""

    @staticmethod
    def _require_scope(user_id: str, tenant_id: str) -> tuple[str, str]:
        tenant = str(tenant_id or "").strip()
        user = str(user_id or "").strip()
        if not tenant or tenant == "default":
            raise ValueError("personalization tenant_id must be explicit and non-default")
        if not user:
            raise ValueError("personalization user_id must be explicit")
        uuid.UUID(tenant)
        uuid.UUID(user)
        return user, tenant

    async def health_check(self) -> UserModelHealthStatus:
        try:
            # Health is intentionally shallow: availability, not synthetic readiness.
            async with async_transaction_scope() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            return UserModelHealthStatus(
                repository=UserModelHealth.UNAVAILABLE,
                memory_integration=UserModelHealth.UNAVAILABLE,
                queue=UserModelHealth.READY,
                snapshot_cache=UserModelHealth.READY,
                evidence_processor=UserModelHealth.DEGRADED,
                overall=UserModelHealth.UNAVAILABLE,
            )

        return UserModelHealthStatus(
            repository=UserModelHealth.READY,
            memory_integration=UserModelHealth.READY,
            queue=UserModelHealth.READY,
            snapshot_cache=UserModelHealth.READY,
            evidence_processor=UserModelHealth.READY,
            overall=UserModelHealth.READY,
        )

    async def list_preferences(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[PreferenceRecord]:
        user, tenant = self._require_scope(user_id, tenant_id)
        now = datetime.utcnow()
        async with async_transaction_scope(tenant_id=tenant) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            pf.fact_id,
                            pf.attribute,
                            pf.value,
                            pf.confidence,
                            pf.source_type,
                            pf.source_ref,
                            pf.valid_from,
                            pf.updated_at
                        FROM public.profile_fact pf
                        JOIN public.memory_event me
                          ON me.event_id = pf.event_id
                        WHERE pf.tenant_id = CAST(:tenant_id AS uuid)
                          AND pf.user_id = CAST(:user_id AS uuid)
                          AND pf.category = 'preference'
                          AND (pf.valid_to IS NULL OR pf.valid_to > :now)
                          AND me.consent_state = 'granted'
                          AND (me.valid_to IS NULL OR me.valid_to > :now)
                        ORDER BY pf.updated_at DESC
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "now": now,
                    },
                )
            ).mappings().all()

        records: list[PreferenceRecord] = []
        for row in rows:
            payload = self._json_object(row["value"])
            key = str(
                payload.get("preference_key")
                or self._preference_key(str(row["attribute"] or "preference"))
            )
            category = self._category_for_key(key)
            scope = self._scope_from_payload(payload)
            stability = self._stability(
                str(payload.get("stability") or PreferenceStability.LONG_TERM.value)
            )
            observed = row["valid_from"] or row["updated_at"] or now
            records.append(
                PreferenceRecord(
                    preference_id=str(row["fact_id"]),
                    user_id=user,
                    tenant_id=tenant,
                    key=key,
                    value=payload.get("value", payload.get("text")),
                    confidence=float(row["confidence"] or 0.0),
                    stability=stability,
                    state=PreferenceState.STABLE,
                    evidence_count=1,
                    contradiction_count=0,
                    first_observed_at=observed,
                    last_observed_at=row["updated_at"] or observed,
                    last_confirmed_at=row["updated_at"] or observed,
                    source_types=[str(row["source_type"] or "memory")],
                    scope=scope,
                    version=1,
                    category=category,
                    metadata={
                        "source_ref": row["source_ref"],
                        "source": "canonical_memory_projection",
                        "domain": payload.get("domain"),
                        "project_id": payload.get("project_id"),
                        "task_id": payload.get("task_id"),
                        "task_type": payload.get("task_type"),
                        "conversation_id": payload.get("conversation_id"),
                        "session_id": payload.get("session_id"),
                    },
                )
            )
        return records

    async def list_goals(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[UserGoal]:
        user, tenant = self._require_scope(user_id, tenant_id)
        now = datetime.utcnow()
        async with async_transaction_scope(tenant_id=tenant) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            g.goal_id,
                            g.description,
                            g.lifecycle_state,
                            g.confidence,
                            g.source_ref,
                            g.target_at,
                            g.valid_from,
                            g.updated_at
                        FROM public.memory_user_goal g
                        JOIN public.memory_event me
                          ON me.event_id = g.event_id
                        WHERE g.tenant_id = CAST(:tenant_id AS uuid)
                          AND g.user_id = CAST(:user_id AS uuid)
                          AND g.lifecycle_state IN (
                              'active', 'blocked', 'paused', 'at_risk', 'satisfied'
                          )
                          AND (g.valid_to IS NULL OR g.valid_to > :now)
                          AND me.consent_state = 'granted'
                          AND (me.valid_to IS NULL OR me.valid_to > :now)
                        ORDER BY g.updated_at DESC
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "user_id": user,
                        "now": now,
                    },
                )
            ).mappings().all()

        return [
            UserGoal(
                goal_id=str(row["goal_id"]),
                user_id=user,
                tenant_id=tenant,
                description=str(row["description"]),
                scope=PreferenceScope.GLOBAL,
                status=self._goal_status(str(row["lifecycle_state"])),
                confidence=float(row["confidence"] or 0.0),
                evidence=[str(row["source_ref"])] if row["source_ref"] else [],
                started_at=row["valid_from"] or row["updated_at"] or now,
                last_observed_at=row["updated_at"] or now,
                target_date=row["target_at"],
                metadata={"source": "canonical_memory_projection"},
            )
            for row in rows
        ]

    async def accumulate_behavior(
        self,
        candidate: BehaviorCandidate,
    ) -> BehaviorPattern:
        user, tenant = self._require_scope(candidate.user_id, candidate.tenant_id)
        observation_id = str(
            candidate.metadata.get("observation_id")
            or candidate.candidate_id
        )
        observed_at_raw = candidate.metadata.get("observed_at")
        observed_at = (
            datetime.fromisoformat(observed_at_raw)
            if isinstance(observed_at_raw, str)
            else datetime.utcnow()
        )
        metadata_payload = {
            **dict(candidate.metadata),
            "observation": candidate.observation,
        }

        async with async_transaction_scope(tenant_id=tenant) as session:
            inserted = (
                await session.execute(
                    text(
                        """
                        INSERT INTO public.personalization_behavior_observation (
                            observation_id,
                            tenant_id,
                            user_id,
                            pattern_type,
                            context_signature,
                            observed_at,
                            metadata_payload,
                            created_at
                        ) VALUES (
                            :observation_id,
                            CAST(:tenant_id AS uuid),
                            CAST(:user_id AS uuid),
                            :pattern_type,
                            :context_signature,
                            :observed_at,
                            CAST(:metadata_payload AS jsonb),
                            now()
                        )
                        ON CONFLICT (
                            tenant_id,
                            user_id,
                            observation_id
                        ) DO NOTHING
                        RETURNING observation_id
                        """
                    ),
                    {
                        "observation_id": observation_id,
                        "tenant_id": tenant,
                        "user_id": user,
                        "pattern_type": candidate.pattern_type,
                        "context_signature": candidate.context_signature,
                        "observed_at": observed_at,
                        "metadata_payload": json.dumps(
                            metadata_payload,
                            default=str,
                        ),
                    },
                )
            ).scalar_one_or_none()

            if inserted is None:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT
                                pattern_id,
                                pattern_type,
                                context_signature,
                                observation_count,
                                confidence,
                                first_seen,
                                last_seen,
                                recurrence,
                                stability,
                                metadata_payload
                            FROM public.personalization_behavior_pattern
                            WHERE tenant_id = CAST(:tenant_id AS uuid)
                              AND user_id = CAST(:user_id AS uuid)
                              AND pattern_type = :pattern_type
                              AND context_signature = :context_signature
                            LIMIT 1
                            """
                        ),
                        {
                            "tenant_id": tenant,
                            "user_id": user,
                            "pattern_type": candidate.pattern_type,
                            "context_signature": candidate.context_signature,
                        },
                    )
                ).mappings().first()
                if row is None:
                    raise RuntimeError(
                        "behavior observation exists without behavior pattern"
                    )
                return self._behavior_from_row(row, user=user, tenant=tenant)

            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO public.personalization_behavior_pattern (
                            pattern_id,
                            tenant_id,
                            user_id,
                            pattern_type,
                            context_signature,
                            observation_count,
                            confidence,
                            first_seen,
                            last_seen,
                            recurrence,
                            stability,
                            metadata_payload,
                            created_at,
                            updated_at
                        ) VALUES (
                            :pattern_id,
                            CAST(:tenant_id AS uuid),
                            CAST(:user_id AS uuid),
                            :pattern_type,
                            :context_signature,
                            1,
                            :confidence,
                            :observed_at,
                            :observed_at,
                            'observed',
                            'session',
                            CAST(:metadata_payload AS jsonb),
                            now(),
                            now()
                        )
                        ON CONFLICT (
                            tenant_id,
                            user_id,
                            pattern_type,
                            context_signature
                        ) DO UPDATE SET
                            observation_count =
                                personalization_behavior_pattern.observation_count + 1,
                            confidence = LEAST(
                                1.0,
                                GREATEST(
                                    personalization_behavior_pattern.confidence,
                                    EXCLUDED.confidence
                                ) + (
                                    0.1 * LEAST(
                                        personalization_behavior_pattern.observation_count,
                                        4
                                    )
                                )
                            ),
                            first_seen = LEAST(
                                personalization_behavior_pattern.first_seen,
                                EXCLUDED.first_seen
                            ),
                            last_seen = GREATEST(
                                personalization_behavior_pattern.last_seen,
                                EXCLUDED.last_seen
                            ),
                            recurrence = CASE
                                WHEN personalization_behavior_pattern.observation_count + 1 >= 3
                                    THEN 'recurring'
                                ELSE 'repeated'
                            END,
                            stability = CASE
                                WHEN personalization_behavior_pattern.observation_count + 1 >= 2
                                    THEN 'short_term'
                                ELSE personalization_behavior_pattern.stability
                            END,
                            metadata_payload =
                                COALESCE(
                                    personalization_behavior_pattern.metadata_payload,
                                    '{}'::jsonb
                                ) || EXCLUDED.metadata_payload,
                            updated_at = now()
                        RETURNING
                            pattern_id,
                            pattern_type,
                            context_signature,
                            observation_count,
                            confidence,
                            first_seen,
                            last_seen,
                            recurrence,
                            stability,
                            metadata_payload
                        """
                    ),
                    {
                        "pattern_id": make_pattern_id(),
                        "tenant_id": tenant,
                        "user_id": user,
                        "pattern_type": candidate.pattern_type,
                        "context_signature": candidate.context_signature,
                        "confidence": candidate.confidence,
                        "observed_at": observed_at,
                        "metadata_payload": json.dumps(
                            metadata_payload,
                            default=str,
                        ),
                    },
                )
            ).mappings().one()

        return self._behavior_from_row(row, user=user, tenant=tenant)

    async def save_behavior(self, pattern: BehaviorPattern) -> None:
        user, tenant = self._require_scope(pattern.user_id, pattern.tenant_id)
        async with async_transaction_scope(tenant_id=tenant) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.personalization_behavior_pattern (
                        pattern_id,
                        tenant_id,
                        user_id,
                        pattern_type,
                        context_signature,
                        observation_count,
                        confidence,
                        first_seen,
                        last_seen,
                        recurrence,
                        stability,
                        metadata_payload,
                        created_at,
                        updated_at
                    ) VALUES (
                        :pattern_id,
                        CAST(:tenant_id AS uuid),
                        CAST(:user_id AS uuid),
                        :pattern_type,
                        :context_signature,
                        :observation_count,
                        :confidence,
                        :first_seen,
                        :last_seen,
                        :recurrence,
                        :stability,
                        CAST(:metadata_payload AS jsonb),
                        now(),
                        now()
                    )
                    ON CONFLICT (
                        tenant_id,
                        user_id,
                        pattern_type,
                        context_signature
                    ) DO UPDATE SET
                        observation_count = EXCLUDED.observation_count,
                        confidence = EXCLUDED.confidence,
                        first_seen = LEAST(
                            personalization_behavior_pattern.first_seen,
                            EXCLUDED.first_seen
                        ),
                        last_seen = GREATEST(
                            personalization_behavior_pattern.last_seen,
                            EXCLUDED.last_seen
                        ),
                        recurrence = EXCLUDED.recurrence,
                        stability = EXCLUDED.stability,
                        metadata_payload = EXCLUDED.metadata_payload,
                        updated_at = now()
                    """
                ),
                {
                    "pattern_id": pattern.pattern_id,
                    "tenant_id": tenant,
                    "user_id": user,
                    "pattern_type": pattern.pattern_type,
                    "context_signature": pattern.context_signature,
                    "observation_count": pattern.observation_count,
                    "confidence": pattern.confidence,
                    "first_seen": pattern.first_seen,
                    "last_seen": pattern.last_seen,
                    "recurrence": pattern.recurrence,
                    "stability": pattern.stability.value,
                    "metadata_payload": json.dumps(pattern.metadata, default=str),
                },
            )

    async def list_behaviors(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[BehaviorPattern]:
        user, tenant = self._require_scope(user_id, tenant_id)
        async with async_transaction_scope(tenant_id=tenant) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            pattern_id,
                            pattern_type,
                            context_signature,
                            observation_count,
                            confidence,
                            first_seen,
                            last_seen,
                            recurrence,
                            stability,
                            metadata_payload
                        FROM public.personalization_behavior_pattern
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND user_id = CAST(:user_id AS uuid)
                        ORDER BY last_seen DESC
                        """
                    ),
                    {"tenant_id": tenant, "user_id": user},
                )
            ).mappings().all()

        return [
            BehaviorPattern(
                pattern_id=str(row["pattern_id"]),
                user_id=user,
                tenant_id=tenant,
                pattern_type=str(row["pattern_type"]),
                context_signature=str(row["context_signature"]),
                observation_count=int(row["observation_count"] or 0),
                confidence=float(row["confidence"] or 0.0),
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                recurrence=str(row["recurrence"]),
                stability=self._stability(str(row["stability"])),
                metadata=self._json_object(row["metadata_payload"]),
            )
            for row in rows
        ]

    @classmethod
    def _behavior_from_row(
        cls,
        row: Any,
        *,
        user: str,
        tenant: str,
    ) -> BehaviorPattern:
        return BehaviorPattern(
            pattern_id=str(row["pattern_id"]),
            user_id=user,
            tenant_id=tenant,
            pattern_type=str(row["pattern_type"]),
            context_signature=str(row["context_signature"]),
            observation_count=int(row["observation_count"] or 0),
            confidence=float(row["confidence"] or 0.0),
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            recurrence=str(row["recurrence"]),
            stability=cls._stability(str(row["stability"])),
            metadata=cls._json_object(row["metadata_payload"]),
        )

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _preference_key(attribute: str) -> str:
        value = str(attribute or "").strip()
        if "." in value:
            return value
        if value == "favorite_color":
            return "interaction.favorite_color"
        return f"interaction.{value or 'preference'}"

    @staticmethod
    def _category_for_key(key: str) -> PreferenceCategory:
        prefix = key.split(".", 1)[0]
        try:
            return PreferenceCategory(prefix)
        except ValueError:
            return PreferenceCategory.INTERACTION

    @staticmethod
    def _scope_from_payload(payload: dict[str, Any]) -> PreferenceScope:
        raw_scope = str(payload.get("scope") or "").strip().casefold()
        if raw_scope:
            try:
                return PreferenceScope(raw_scope)
            except ValueError:
                pass
        if payload.get("session_id"):
            return PreferenceScope.SESSION
        if payload.get("conversation_id"):
            return PreferenceScope.CONVERSATION
        if payload.get("project_id"):
            return PreferenceScope.PROJECT
        if payload.get("task_id") or payload.get("task_type"):
            return PreferenceScope.TASK_TYPE
        if payload.get("domain"):
            return PreferenceScope.DOMAIN
        return PreferenceScope.GLOBAL

    @staticmethod
    def _goal_status(state: str) -> UserGoalStatus:
        mapping = {
            "active": UserGoalStatus.ACTIVE,
            "paused": UserGoalStatus.PAUSED,
            "completed": UserGoalStatus.COMPLETED,
            "abandoned": UserGoalStatus.ABANDONED,
        }
        return mapping.get(state, UserGoalStatus.ACTIVE)

    @staticmethod
    def _stability(value: str) -> PreferenceStability:
        try:
            return PreferenceStability(value)
        except ValueError:
            return PreferenceStability.SHORT_TERM


__all__ = ["PostgresPersonalizationRepository"]
