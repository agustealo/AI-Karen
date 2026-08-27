"""PostgreSQL derived projections from governed NeuroVault commits.

Canonical durable truth is written first by NeuroVault. This projector may then
materialize profile, episodic, procedural, Redis, and graph views using the
committed event ID as provenance. It never decides whether a memory is allowed
to be durable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from ai_karen_engine.core.memory.projections import get_projection_manager
from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .ledger_models import MemoryEpisode, ProfileFact, ProjectionStatus
from .procedural_models import MemoryProcedure


class PostgresDerivedMemoryProjector:
    """Materialize rebuildable views after a successful governed commit."""

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

        results = await get_projection_manager().project_event(event_data, assertion_data)
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
            episode_stmt = select(MemoryEpisode.episode_id).where(
                MemoryEpisode.event_id == event_uuid
            ).limit(1)
            if (await session.execute(episode_stmt)).scalar_one_or_none() is None:
                session.add(
                    MemoryEpisode(
                        event_id=event_uuid,
                        tenant_id=tenant_uuid,
                        user_id=user_uuid,
                        session_id=metadata.get("session_id"),
                        summary=str(metadata.get("episode_summary") or signal.text[:240]),
                        snapshot_data={
                            "signal_type": signal.signal_type,
                            "text": signal.text,
                            "entities": list(signal.entities or []),
                            "keywords": list(signal.keywords or []),
                            "metadata": metadata,
                        },
                    )
                )

            if signal.signal_type == "preference":
                fact_stmt = select(ProfileFact.fact_id).where(
                    ProfileFact.event_id == event_uuid
                ).limit(1)
                if (await session.execute(fact_stmt)).scalar_one_or_none() is None:
                    session.add(
                        ProfileFact(
                            event_id=event_uuid,
                            tenant_id=tenant_uuid,
                            user_id=user_uuid,
                            category="preference",
                            attribute=str(metadata.get("attribute") or "user_preference"),
                            value={
                                "text": signal.text,
                                "keywords": list(signal.keywords or []),
                                "entities": list(signal.entities or []),
                            },
                            confidence=confidence,
                            source_type=source_type,
                            source_ref=source_ref,
                            valid_from=self._datetime(metadata.get("valid_from")),
                            valid_to=self._datetime(metadata.get("valid_to")),
                        )
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
                            valid_from=self._datetime(metadata.get("valid_from")) or datetime.utcnow(),
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
        # The event's tenant is already enforced by the manager's projection
        # calls. Status rows are event-scoped and only record stores that actually
        # ran; retired stores never receive synthetic "completed" statuses.
        for store, ok in results.items():
            # Resolve tenant from the canonical event indirectly through the
            # projection's event scope is unnecessary here; status writes occur
            # in the same governed write pipeline and are not user-facing truth.
            # We still use the canonical engine transaction via the event's
            # existing RLS-aware caller in the next method invocation.
            await self._upsert_projection_status(event_uuid, store, ok)

    async def _upsert_projection_status(
        self,
        event_uuid: uuid.UUID,
        store: str,
        ok: bool,
    ) -> None:
        # ProjectionStatus itself has no tenant_id column, so RLS is inherited
        # through event ownership rather than row-local scope. The canonical
        # schema's uniqueness constraint prevents duplicate store claims.
        from ai_karen_engine.persistence.postgres import get_postgres_engine

        engine = get_postgres_engine()
        async with engine.get_async_session() as session:
            stmt = select(ProjectionStatus).where(
                ProjectionStatus.event_id == event_uuid,
                ProjectionStatus.target_store == store,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = ProjectionStatus(
                    event_id=event_uuid,
                    target_store=store,
                    status="completed" if ok else "failed",
                    retry_count=0,
                    last_error=None if ok else "projection_returned_false",
                )
                session.add(row)
            else:
                row.status = "completed" if ok else "failed"
                row.last_error = None if ok else "projection_returned_false"

    @staticmethod
    def _memory_type(signal_type: str) -> str:
        if signal_type in {"workflow", "procedure", "tool_use"}:
            return "procedural"
        if signal_type in {"preference", "fact", "entity"}:
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
    def _datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None


__all__ = ["PostgresDerivedMemoryProjector"]
