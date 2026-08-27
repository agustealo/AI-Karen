"""PostgreSQL implementation of memory control/governance operations.

This adapter is intentionally narrow: operator inspection, consent governance,
retention policy administration, and promoted-artifact export. It reuses the
canonical SQLAlchemy session authority and existing memory ledger tables. It is
not a recall service and cannot write ordinary durable memories.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select

from ai_karen_engine.core.memory.control import MemoryControlPort

from .ledger_models import (
    ConsentScope,
    ContradictionEvent,
    MemoryAssertion,
    MemoryEpisode,
    MemoryEvent,
    ProfileFact,
    ProjectionStatus,
    RetentionPolicy,
)


class PostgresMemoryControlRepository(MemoryControlPort):
    """SQLAlchemy-backed memory control persistence adapter."""

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

    @staticmethod
    def _uuid(value: str | None, *, field_name: str) -> uuid.UUID | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        try:
            return uuid.UUID(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid UUID") from exc

    @staticmethod
    def _dt(value: Any) -> str | None:
        if value is None:
            return None
        return value.isoformat() if isinstance(value, datetime) else str(value)

    @classmethod
    def _event_payload(cls, row: MemoryEvent) -> dict[str, Any]:
        return {
            "event_id": str(row.event_id),
            "tenant_id": str(row.tenant_id),
            "user_id": str(row.user_id),
            "source_type": row.source_type,
            "source_ref": row.source_ref,
            "payload_hash": row.payload_hash,
            "confidence": row.confidence,
            "scope": row.scope,
            "sensitivity_class": row.sensitivity_class,
            "consent_state": row.consent_state,
            "valid_from": cls._dt(row.valid_from),
            "valid_to": cls._dt(row.valid_to),
            "supersedes": str(row.supersedes) if row.supersedes else None,
            "event_type": row.event_type,
            "created_at": cls._dt(row.created_at),
            "updated_at": cls._dt(row.updated_at),
            "payload": row.payload,
        }

    async def inspect(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(user_id, field_name="user_id")
        session_factory = self._resolve_session_factory()

        event_filters: list[Any] = []
        assertion_filters: list[Any] = []
        fact_filters: list[Any] = []
        episode_filters: list[Any] = []
        consent_filters: list[Any] = []
        if tenant_uuid is not None:
            event_filters.append(MemoryEvent.tenant_id == tenant_uuid)
            assertion_filters.append(MemoryAssertion.tenant_id == tenant_uuid)
            fact_filters.append(ProfileFact.tenant_id == tenant_uuid)
            episode_filters.append(MemoryEpisode.tenant_id == tenant_uuid)
            consent_filters.append(ConsentScope.tenant_id == tenant_uuid)
        if user_uuid is not None:
            event_filters.append(MemoryEvent.user_id == user_uuid)
            assertion_filters.append(MemoryAssertion.user_id == user_uuid)
            fact_filters.append(ProfileFact.user_id == user_uuid)
            episode_filters.append(MemoryEpisode.user_id == user_uuid)
            consent_filters.append(ConsentScope.user_id == user_uuid)

        async with session_factory() as session:
            async def _rows(model: Any, filters: list[Any], order_by: Any) -> list[Any]:
                stmt = select(model)
                if filters:
                    stmt = stmt.where(*filters)
                result = await session.execute(stmt.order_by(order_by.desc()).limit(limit))
                return list(result.scalars().all())

            events = await _rows(MemoryEvent, event_filters, MemoryEvent.created_at)
            assertions = await _rows(
                MemoryAssertion, assertion_filters, MemoryAssertion.created_at
            )
            facts = await _rows(ProfileFact, fact_filters, ProfileFact.created_at)
            episodes = await _rows(MemoryEpisode, episode_filters, MemoryEpisode.created_at)
            consents = await _rows(ConsentScope, consent_filters, ConsentScope.granted_at)

            contradiction_stmt = select(ContradictionEvent).join(
                MemoryEvent,
                MemoryEvent.event_id == ContradictionEvent.event_id,
            )
            if tenant_uuid is not None:
                contradiction_stmt = contradiction_stmt.where(
                    MemoryEvent.tenant_id == tenant_uuid
                )
            if user_uuid is not None:
                contradiction_stmt = contradiction_stmt.where(
                    MemoryEvent.user_id == user_uuid
                )
            contradiction_result = await session.execute(
                contradiction_stmt.order_by(ContradictionEvent.created_at.desc()).limit(limit)
            )
            contradictions = list(contradiction_result.scalars().all())

            retention_stmt = select(RetentionPolicy)
            if tenant_uuid is not None:
                retention_stmt = retention_stmt.where(
                    (RetentionPolicy.tenant_id == tenant_uuid)
                    | (RetentionPolicy.tenant_id.is_(None))
                )
            retention_result = await session.execute(
                retention_stmt.order_by(RetentionPolicy.updated_at.desc()).limit(limit)
            )
            retentions = list(retention_result.scalars().all())

            projection_stmt = select(ProjectionStatus).join(
                MemoryEvent,
                MemoryEvent.event_id == ProjectionStatus.event_id,
            )
            if tenant_uuid is not None:
                projection_stmt = projection_stmt.where(MemoryEvent.tenant_id == tenant_uuid)
            if user_uuid is not None:
                projection_stmt = projection_stmt.where(MemoryEvent.user_id == user_uuid)
            projection_result = await session.execute(
                projection_stmt.order_by(ProjectionStatus.updated_at.desc()).limit(limit)
            )
            projections = list(projection_result.scalars().all())

            counts: dict[str, int] = {}
            for name, model, filters in (
                ("events", MemoryEvent, event_filters),
                ("assertions", MemoryAssertion, assertion_filters),
                ("profile_facts", ProfileFact, fact_filters),
                ("episodes", MemoryEpisode, episode_filters),
                ("consent_scopes", ConsentScope, consent_filters),
            ):
                stmt = select(func.count()).select_from(model)
                if filters:
                    stmt = stmt.where(*filters)
                result = await session.execute(stmt)
                counts[name] = int(result.scalar_one() or 0)

            contradiction_count = select(func.count()).select_from(ContradictionEvent).join(
                MemoryEvent,
                MemoryEvent.event_id == ContradictionEvent.event_id,
            )
            if tenant_uuid is not None:
                contradiction_count = contradiction_count.where(
                    MemoryEvent.tenant_id == tenant_uuid
                )
            if user_uuid is not None:
                contradiction_count = contradiction_count.where(
                    MemoryEvent.user_id == user_uuid
                )
            result = await session.execute(contradiction_count)
            counts["contradictions"] = int(result.scalar_one() or 0)

            retention_count = select(func.count()).select_from(RetentionPolicy)
            if tenant_uuid is not None:
                retention_count = retention_count.where(
                    (RetentionPolicy.tenant_id == tenant_uuid)
                    | (RetentionPolicy.tenant_id.is_(None))
                )
            result = await session.execute(retention_count)
            counts["retention_policies"] = int(result.scalar_one() or 0)

        return {
            "status": "success",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "limit": limit,
            "counts": counts,
            "recent_events": [self._event_payload(row) for row in events],
            "recent_assertions": [
                {
                    "assertion_id": str(row.assertion_id),
                    "event_id": str(row.event_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "content": row.content,
                    "confidence": row.confidence,
                    "scope": row.scope,
                    "sensitivity_class": row.sensitivity_class,
                    "consent_state": row.consent_state,
                    "valid_from": self._dt(row.valid_from),
                    "valid_to": self._dt(row.valid_to),
                    "supersedes": str(row.supersedes) if row.supersedes else None,
                    "created_at": self._dt(row.created_at),
                    "updated_at": self._dt(row.updated_at),
                }
                for row in assertions
            ],
            "recent_profile_facts": [
                {
                    "fact_id": str(row.fact_id),
                    "event_id": str(row.event_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "category": row.category,
                    "attribute": row.attribute,
                    "value": row.value,
                    "confidence": row.confidence,
                    "source_type": row.source_type,
                    "source_ref": row.source_ref,
                    "valid_from": self._dt(row.valid_from),
                    "valid_to": self._dt(row.valid_to),
                    "supersedes": str(row.supersedes) if row.supersedes else None,
                    "created_at": self._dt(row.created_at),
                    "updated_at": self._dt(row.updated_at),
                }
                for row in facts
            ],
            "recent_episodes": [
                {
                    "episode_id": str(row.episode_id),
                    "event_id": str(row.event_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "session_id": row.session_id,
                    "episode_group_id": str(row.episode_group_id),
                    "started_at": self._dt(row.started_at),
                    "ended_at": self._dt(row.ended_at),
                    "boundary_reason": row.boundary_reason,
                    "summary": row.summary,
                    "snapshot_data": row.snapshot_data,
                    "created_at": self._dt(row.created_at),
                }
                for row in episodes
            ],
            "open_contradictions": [
                {
                    "contradiction_id": str(row.contradiction_id),
                    "event_id": str(row.event_id),
                    "source_assertion_id": str(row.source_assertion_id),
                    "target_assertion_id": str(row.target_assertion_id),
                    "resolution_status": row.resolution_status,
                    "created_at": self._dt(row.created_at),
                    "resolved_at": self._dt(row.resolved_at),
                }
                for row in contradictions
            ],
            "consent_scopes": [self._consent_payload(row) for row in consents],
            "retention_policies": [self._retention_payload(row) for row in retentions],
            "projection_status": [
                {
                    "projection_id": str(row.projection_id),
                    "event_id": str(row.event_id),
                    "target_store": row.target_store,
                    "status": row.status,
                    "retry_count": row.retry_count,
                    "last_error": row.last_error,
                    "created_at": self._dt(row.created_at),
                    "updated_at": self._dt(row.updated_at),
                }
                for row in projections
            ],
        }

    @classmethod
    def _consent_payload(cls, row: ConsentScope) -> dict[str, Any]:
        return {
            "scope_id": str(row.scope_id),
            "tenant_id": str(row.tenant_id),
            "user_id": str(row.user_id),
            "scope_name": row.scope_name,
            "is_granted": bool(row.is_granted),
            "granted_at": cls._dt(row.granted_at),
            "revoked_at": cls._dt(row.revoked_at),
        }

    @classmethod
    def _retention_payload(cls, row: RetentionPolicy) -> dict[str, Any]:
        return {
            "policy_id": str(row.policy_id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "memory_class": row.memory_class,
            "ttl_days": row.ttl_days,
            "created_at": cls._dt(row.created_at),
            "updated_at": cls._dt(row.updated_at),
        }

    async def list_consent_scopes(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        if tenant_uuid is None:
            raise ValueError("tenant_id is required")
        user_uuid = self._uuid(user_id, field_name="user_id")
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(ConsentScope).where(ConsentScope.tenant_id == tenant_uuid)
            if user_uuid is not None:
                stmt = stmt.where(ConsentScope.user_id == user_uuid)
            result = await session.execute(stmt.order_by(ConsentScope.granted_at.desc()))
            rows = list(result.scalars().all())
        return {"status": "success", "items": [self._consent_payload(row) for row in rows]}

    async def set_consent_scope(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope_name: str,
        granted: bool,
    ) -> dict[str, Any]:
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(user_id, field_name="user_id")
        if tenant_uuid is None or user_uuid is None:
            raise ValueError("tenant_id and user_id are required")
        scope_name = str(scope_name or "").strip()
        if not scope_name:
            raise ValueError("scope_name is required")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(ConsentScope).where(
                ConsentScope.tenant_id == tenant_uuid,
                ConsentScope.user_id == user_uuid,
                ConsentScope.scope_name == scope_name,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                row = ConsentScope(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    scope_name=scope_name,
                    is_granted=bool(granted),
                    granted_at=now,
                    revoked_at=None if granted else now,
                )
                session.add(row)
            else:
                row.is_granted = bool(granted)
                row.revoked_at = None if granted else now
                if granted and row.granted_at is None:
                    row.granted_at = now
            await session.commit()
            await session.refresh(row)
            payload = self._consent_payload(row)
        return {"status": "success", **payload}

    async def list_retention_policies(
        self,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(RetentionPolicy)
            if tenant_uuid is not None:
                stmt = stmt.where(
                    (RetentionPolicy.tenant_id == tenant_uuid)
                    | (RetentionPolicy.tenant_id.is_(None))
                )
            result = await session.execute(stmt.order_by(RetentionPolicy.updated_at.desc()))
            rows = list(result.scalars().all())
        return {"status": "success", "items": [self._retention_payload(row) for row in rows]}

    async def set_retention_policy(
        self,
        *,
        memory_class: str,
        ttl_days: int | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        memory_class = str(memory_class or "").strip()
        if not memory_class:
            raise ValueError("memory_class is required")
        if ttl_days is not None and int(ttl_days) < 1:
            raise ValueError("ttl_days must be positive when provided")
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(RetentionPolicy).where(
                RetentionPolicy.memory_class == memory_class,
                RetentionPolicy.tenant_id.is_(None)
                if tenant_uuid is None
                else RetentionPolicy.tenant_id == tenant_uuid,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                row = RetentionPolicy(
                    tenant_id=tenant_uuid,
                    memory_class=memory_class,
                    ttl_days=ttl_days,
                )
                session.add(row)
            else:
                row.ttl_days = ttl_days
            await session.commit()
            await session.refresh(row)
            payload = self._retention_payload(row)
        return {"status": "success", **payload}

    async def export_promoted_artifacts(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        tenant_uuid = self._uuid(tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(user_id, field_name="user_id")
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            fact_stmt = select(ProfileFact)
            assertion_stmt = select(MemoryAssertion)
            if tenant_uuid is not None:
                fact_stmt = fact_stmt.where(ProfileFact.tenant_id == tenant_uuid)
                assertion_stmt = assertion_stmt.where(MemoryAssertion.tenant_id == tenant_uuid)
            if user_uuid is not None:
                fact_stmt = fact_stmt.where(ProfileFact.user_id == user_uuid)
                assertion_stmt = assertion_stmt.where(MemoryAssertion.user_id == user_uuid)
            fact_result = await session.execute(
                fact_stmt.order_by(ProfileFact.created_at.desc()).limit(limit)
            )
            assertion_result = await session.execute(
                assertion_stmt.order_by(MemoryAssertion.created_at.desc()).limit(limit)
            )
            facts = list(fact_result.scalars().all())
            assertions = list(assertion_result.scalars().all())

        artifacts: list[dict[str, Any]] = []
        for row in facts:
            artifacts.append(
                {
                    "artifact_id": str(row.fact_id),
                    "artifact_type": "user_preference"
                    if row.category == "preference"
                    else "long_term_fact",
                    "source_tier": "ltm",
                    "user_id": str(row.user_id),
                    "tenant_id": str(row.tenant_id),
                    "session_id": str(row.event_id),
                    "thread_id": None,
                    "content": {
                        "category": row.category,
                        "attribute": row.attribute,
                        "value": row.value,
                        "confidence": row.confidence,
                    },
                    "importance_score": float(row.confidence or 0.0),
                    "retention_score": 1.0,
                    "privacy_tags": ["normal"],
                    "training_eligibility": "review",
                    "metadata": {
                        "source": "profile_fact",
                        "source_ref": row.source_ref,
                        "valid_from": self._dt(row.valid_from),
                        "valid_to": self._dt(row.valid_to),
                    },
                }
            )
            if len(artifacts) >= limit:
                break
        if len(artifacts) < limit:
            for row in assertions:
                artifacts.append(
                    {
                        "artifact_id": str(row.assertion_id),
                        "artifact_type": "long_term_fact",
                        "source_tier": "ltm",
                        "user_id": str(row.user_id),
                        "tenant_id": str(row.tenant_id),
                        "session_id": str(row.event_id),
                        "thread_id": None,
                        "content": {
                            "content": row.content,
                            "scope": row.scope,
                            "confidence": row.confidence,
                        },
                        "importance_score": float(row.confidence or 0.0),
                        "retention_score": 1.0,
                        "privacy_tags": [row.sensitivity_class or "normal"],
                        "training_eligibility": "review",
                        "metadata": {
                            "source": "memory_assertion",
                            "valid_from": self._dt(row.valid_from),
                            "valid_to": self._dt(row.valid_to),
                            "consent_state": row.consent_state,
                        },
                    }
                )
                if len(artifacts) >= limit:
                    break

        return {
            "status": "success",
            "count": len(artifacts),
            "limit": limit,
            "artifacts": artifacts,
        }


__all__ = ["PostgresMemoryControlRepository"]
