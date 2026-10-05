"""PostgreSQL derived projections from governed NeuroVault commits.

Canonical durable truth is written first by NeuroVault. This projector may then
materialize profile, episodic, procedural, goal, prospective, STM, and graph
views using the committed event ID as provenance. It never decides whether a
memory is allowed to be durable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from ai_karen_engine.core.memory.projections import ProjectionManager
from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import (
    MemoryEpisode,
    MemoryProspectiveItem,
    MemoryUserGoal,
    ProfileFact,
    ProjectionStatus,
)
from .procedural_models import MemoryProcedure


class PostgresDerivedMemoryProjector:
    """Materialize rebuildable views after a successful governed commit."""

    def __init__(self, projection_manager: ProjectionManager) -> None:
        self._projection_manager = projection_manager

    async def project(
        self,
        *,
        tenant_id: str,
        user_id: str,
        event_id: str,
        memory_id: str,
        signal: MemorySignal,
        confidence: float,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        tenant_uuid = uuid.UUID(str(tenant_id))
        user_uuid = uuid.UUID(str(user_id))
        event_uuid = uuid.UUID(str(event_id))
        merged = dict(signal.metadata or {})
        merged.update(metadata or {})

        await self._project_relational_views(
            tenant_uuid=tenant_uuid,
            user_uuid=user_uuid,
            event_uuid=event_uuid,
            signal=signal,
            confidence=confidence,
            source_type=source_type,
            source_ref=source_ref,
            metadata=merged,
        )

        event_data = {
            "event_id": str(event_uuid),
            "tenant_id": str(tenant_uuid),
            "user_id": str(user_uuid),
            "conversation_id": merged.get("conversation_id"),
            "session_id": merged.get("session_id"),
            "memory_type": self._memory_type(signal.signal_type),
            "importance": confidence,
            "source": source_type,
            "source_type": source_type,
            "source_ref": source_ref,
            "created_at": datetime.utcnow().isoformat(),
            "payload": {
                "text": signal.text,
                "summary": merged.get("episode_summary") or signal.text[:240],
                "entities": list(signal.entities or []),
                "keywords": list(signal.keywords or []),
                "signal_type": signal.signal_type,
                "semantic_class": merged.get("semantic_class"),
                "episode_group_id": merged.get("episode_group_id"),
                "episode_boundary_reason": merged.get("episode_boundary_reason"),
                "metadata": merged,
            },
        }
        assertion_data = {
            "assertion_id": memory_id,
            "event_id": str(event_uuid),
            "text": signal.text,
            "confidence": confidence,
            "polarity": merged.get("polarity"),
            "contradicts": self._listify(merged.get("contradicts")),
            "reinforces": self._listify(merged.get("reinforces")),
        }

        results = await self._projection_manager.project_event(event_data, assertion_data)
        await self._record_projection_statuses(event_uuid=event_uuid, results=results)
        return results

    async def _project_relational_views(
        self,
        *,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_uuid: uuid.UUID,
        signal: MemorySignal,
        confidence: float,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any],
    ) -> None:
        async with async_transaction_scope(tenant_id=str(tenant_uuid)) as session:
            await self._project_episode(
                session=session,
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
                event_uuid=event_uuid,
                signal=signal,
                metadata=metadata,
            )

            if signal.signal_type in {"identity_fact", "preference"}:
                await self._project_profile_fact(
                    session=session,
                    tenant_uuid=tenant_uuid,
                    user_uuid=user_uuid,
                    event_uuid=event_uuid,
                    signal=signal,
                    confidence=confidence,
                    source_type=source_type,
                    source_ref=source_ref,
                    metadata=metadata,
                )

            if signal.signal_type == "goal":
                await self._project_goal(
                    session=session,
                    tenant_uuid=tenant_uuid,
                    user_uuid=user_uuid,
                    event_uuid=event_uuid,
                    signal=signal,
                    confidence=confidence,
                    source_type=source_type,
                    source_ref=source_ref,
                    metadata=metadata,
                )

            if signal.signal_type == "prospective_event":
                await self._project_prospective_item(
                    session=session,
                    tenant_uuid=tenant_uuid,
                    user_uuid=user_uuid,
                    event_uuid=event_uuid,
                    signal=signal,
                    confidence=confidence,
                    source_type=source_type,
                    source_ref=source_ref,
                    metadata=metadata,
                )

            if signal.signal_type in {"workflow", "procedure", "tool_use"}:
                procedure_stmt = select(MemoryProcedure.procedure_id).where(
                    MemoryProcedure.source_event_id == event_uuid
                ).limit(1)
                if (await session.execute(procedure_stmt)).scalar_one_or_none() is None:
                    session.add(
                        MemoryProcedure(
                            source_event_id=event_uuid,
                            tenant_id=tenant_uuid,
                            user_id=user_uuid,
                            name=str(metadata.get("procedure_name") or signal.text[:255]),
                            trigger_patterns=list(
                                metadata.get("trigger_patterns")
                                or signal.keywords
                                or []
                            ),
                            tool_sequence=list(metadata.get("tool_sequence") or []),
                            success_count=max(0, int(metadata.get("success_count") or 0)),
                            failure_count=max(0, int(metadata.get("failure_count") or 0)),
                            confidence=max(0.0, min(1.0, confidence)),
                            lifecycle_state="active",
                            valid_from=self._datetime(metadata.get("valid_from"))
                            or datetime.utcnow(),
                            valid_to=self._datetime(metadata.get("valid_to")),
                            metadata_payload=metadata,
                        )
                    )

    async def _project_episode(
        self,
        *,
        session: Any,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_uuid: uuid.UUID,
        signal: MemorySignal,
        metadata: dict[str, Any],
    ) -> None:
        episode_stmt = select(MemoryEpisode.episode_id).where(
            MemoryEpisode.event_id == event_uuid
        ).limit(1)
        if (await session.execute(episode_stmt)).scalar_one_or_none() is not None:
            return

        group_uuid = self._uuid_or_default(
            metadata.get("episode_group_id"), event_uuid
        )
        started_at = (
            self._datetime(metadata.get("episode_started_at"))
            or datetime.utcnow()
        )
        session.add(
            MemoryEpisode(
                event_id=event_uuid,
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                session_id=metadata.get("session_id"),
                episode_group_id=group_uuid,
                started_at=started_at,
                ended_at=self._datetime(metadata.get("episode_ended_at")),
                boundary_reason=str(
                    metadata.get("episode_boundary_reason") or "continuation"
                ),
                context_payload={
                    "goal_key": metadata.get("episode_goal_key"),
                    "project_key": metadata.get("episode_project_key"),
                    "turn_count": metadata.get("episode_turn_count"),
                    "episode_new": metadata.get("episode_new"),
                    "episode_state_persisted": metadata.get(
                        "episode_state_persisted"
                    ),
                },
                summary=str(metadata.get("episode_summary") or signal.text[:240]),
                snapshot_data={
                    "signal_type": signal.signal_type,
                    "semantic_class": metadata.get("semantic_class"),
                    "text": signal.text,
                    "entities": list(signal.entities or []),
                    "keywords": list(signal.keywords or []),
                    "metadata": metadata,
                },
            )
        )

    async def _project_profile_fact(
        self,
        *,
        session: Any,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_uuid: uuid.UUID,
        signal: MemorySignal,
        confidence: float,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any],
    ) -> None:
        existing_event = (
            await session.execute(
                select(ProfileFact.fact_id)
                .where(ProfileFact.event_id == event_uuid)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_event is not None:
            return

        category = str(
            metadata.get("category")
            or ("identity" if signal.signal_type == "identity_fact" else "preference")
        )
        attribute = str(
            metadata.get("attribute")
            or (
                "identity_fact"
                if signal.signal_type == "identity_fact"
                else "user_preference"
            )
        )
        normalized_value = metadata.get("normalized_value")
        value: dict[str, Any] = {
            "value": normalized_value if normalized_value is not None else signal.text,
            "text": signal.text,
            "semantic_class": metadata.get("semantic_class"),
        }
        if signal.keywords:
            value["keywords"] = list(signal.keywords)
        if signal.entities:
            value["entities"] = list(signal.entities)

        current = (
            await session.execute(
                select(ProfileFact)
                .where(
                    ProfileFact.tenant_id == tenant_uuid,
                    ProfileFact.user_id == user_uuid,
                    ProfileFact.category == category,
                    ProfileFact.attribute == attribute,
                    ProfileFact.valid_to.is_(None),
                )
                .order_by(ProfileFact.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        valid_from = self._datetime(metadata.get("valid_from")) or datetime.utcnow()
        if current is not None and current.value == value:
            current.confidence = max(float(current.confidence or 0.0), confidence)
            current.updated_at = datetime.utcnow()
            return

        supersedes = None
        if current is not None:
            current.valid_to = valid_from
            current.updated_at = datetime.utcnow()
            supersedes = current.fact_id

        session.add(
            ProfileFact(
                event_id=event_uuid,
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                category=category,
                attribute=attribute,
                value=value,
                confidence=confidence,
                source_type=source_type,
                source_ref=source_ref,
                valid_from=valid_from,
                valid_to=self._datetime(metadata.get("valid_to")),
                supersedes=supersedes,
            )
        )

    async def _project_goal(
        self,
        *,
        session: Any,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_uuid: uuid.UUID,
        signal: MemorySignal,
        confidence: float,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any],
    ) -> None:
        exists = (
            await session.execute(
                select(MemoryUserGoal.goal_id)
                .where(MemoryUserGoal.event_id == event_uuid)
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists is not None:
            return

        session.add(
            MemoryUserGoal(
                event_id=event_uuid,
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                description=str(metadata.get("description") or signal.text),
                goal_type=str(metadata.get("goal_type") or "explicit"),
                lifecycle_state=str(metadata.get("lifecycle_state") or "active"),
                confidence=confidence,
                source_type=source_type,
                source_ref=source_ref,
                target_text=self._optional_text(metadata.get("target_text")),
                target_at=self._datetime(metadata.get("target_at")),
                valid_from=self._datetime(metadata.get("valid_from"))
                or datetime.utcnow(),
                valid_to=self._datetime(metadata.get("valid_to")),
                metadata_payload=metadata,
            )
        )

    async def _project_prospective_item(
        self,
        *,
        session: Any,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_uuid: uuid.UUID,
        signal: MemorySignal,
        confidence: float,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any],
    ) -> None:
        exists = (
            await session.execute(
                select(MemoryProspectiveItem.prospective_id)
                .where(MemoryProspectiveItem.event_id == event_uuid)
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists is not None:
            return

        session.add(
            MemoryProspectiveItem(
                event_id=event_uuid,
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                event_type=str(metadata.get("event_type") or "user_event"),
                description=signal.text,
                temporal_text=self._optional_text(metadata.get("temporal_text")),
                target_at=self._datetime(metadata.get("target_at")),
                lifecycle_state=str(metadata.get("lifecycle_state") or "dormant"),
                confidence=confidence,
                source_type=source_type,
                source_ref=source_ref,
                valid_from=self._datetime(metadata.get("valid_from"))
                or datetime.utcnow(),
                valid_to=self._datetime(metadata.get("valid_to")),
                metadata_payload=metadata,
            )
        )

    async def _record_projection_statuses(
        self,
        *,
        event_uuid: uuid.UUID,
        results: dict[str, bool],
    ) -> None:
        for store, ok in results.items():
            await self._upsert_projection_status(event_uuid, store, ok)

    async def _upsert_projection_status(
        self,
        event_uuid: uuid.UUID,
        store: str,
        ok: bool,
    ) -> None:
        from ai_karen_engine.persistence.postgres import get_postgres_engine

        engine = get_postgres_engine()
        async with engine.get_async_session() as session:
            stmt = select(ProjectionStatus).where(
                ProjectionStatus.event_id == event_uuid,
                ProjectionStatus.target_store == store,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                session.add(
                    ProjectionStatus(
                        event_id=event_uuid,
                        target_store=store,
                        status="completed" if ok else "failed",
                        retry_count=0,
                        last_error=None if ok else "projection_returned_false",
                    )
                )
            else:
                row.status = "completed" if ok else "failed"
                row.last_error = None if ok else "projection_returned_false"

    @staticmethod
    def _memory_type(signal_type: str) -> str:
        if signal_type in {"workflow", "procedure", "tool_use"}:
            return "procedural"
        if signal_type in {"identity_fact", "preference", "fact", "entity", "goal"}:
            return "semantic"
        return "episodic"

    @staticmethod
    def _listify(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo is not None else value
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
            except ValueError:
                return None
        return None

    @staticmethod
    def _uuid_or_default(value: Any, default: uuid.UUID) -> uuid.UUID:
        try:
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return default


__all__ = ["PostgresDerivedMemoryProjector"]
