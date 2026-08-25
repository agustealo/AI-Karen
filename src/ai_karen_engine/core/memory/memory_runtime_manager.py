"""
Memory Runtime Manager for AI Karen.

This module is the adaptive-memory write authority and also preserves the
legacy package-level API used by the rest of the application:
- init_memory()
- close()
- recall_context()
- update_memory()
- export_promoted_artifacts()
- get_metrics()

The canonical write path is:
extraction -> scoring -> ledger write -> projection dispatch -> offline synthesis.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai_karen_engine.core.logging import get_logger

from ..runtime.resilience import get_feature_flags
from .ledger_models import (
    ConsentScope,
    ContradictionEvent,
    MemoryAssertion,
    MemoryEpisode,
    MemoryEvent,
    ProfileFact,
    ProjectionStatus,
    ReinforcementEvent,
    RetentionPolicy,
)
from .neuro.activation_gate import decide_activation_mode
from .scoring import MemoryWorthinessScorer
from .signals import MemorySignal, get_signal_pipeline

logger = get_logger(__name__)


_METRICS: dict[str, int] = {
    "interactions_processed": 0,
    "signals_extracted": 0,
    "signals_admitted": 0,
    "ledger_writes": 0,
    "ledger_duplicates": 0,
    "projection_dispatches": 0,
    "projection_failures": 0,
    "profile_synthesis_requests": 0,
    "echocore_candidates": 0,
    "recall_requests": 0,
    "recall_hits": 0,
    "shadow_mode_runs": 0,
    "inspector_requests": 0,
    "consent_updates": 0,
    "retention_updates": 0,
}


def _coerce_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        with suppress(ValueError):
            return datetime.fromisoformat(value)
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        try:
            return value.value
        except Exception:
            return str(value)
    return value


class MemoryRuntimeManager:
    """Single write authority for Karen's memory system."""

    def __init__(self, retrieval_adapter=None, consolidation_adapter=None):
        self.signal_pipeline = get_signal_pipeline()
        self.worthiness_scorer = MemoryWorthinessScorer()
        self.flags = get_feature_flags()
        self._db_session_factory = None
        self._projection_workers: dict[str, Any] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._retrieval_adapter = retrieval_adapter
        self._consolidation_adapter = consolidation_adapter

    def set_retrieval_adapter(self, adapter) -> None:
        """Set the retrieval port adapter (CORE-SPLIT-2 migration)."""
        self._retrieval_adapter = adapter

    def set_consolidation_adapter(self, adapter) -> None:
        """Set the consolidation port adapter (CORE-SPLIT-2 migration)."""
        self._consolidation_adapter = adapter

    def set_db_session_factory(self, factory):
        """Set the SQLAlchemy async session factory."""
        self._db_session_factory = factory

    def _ensure_db_session_factory(self) -> None:
        """Try to bind the runtime manager to the application's async DB session."""
        if self._db_session_factory is not None:
            return

        try:
            from ai_karen_engine.database.client import db_client

            if db_client and hasattr(db_client, "get_async_session"):
                self._db_session_factory = db_client.get_async_session
                logger.info("Bound memory runtime manager to the database async session factory")
        except Exception as exc:
            logger.debug("Database session factory could not be auto-bound: %s", exc)

    async def recall_context(
        self,
        user_id: Any,
        query: str,
        top_k: int = 10,
        tiers: Sequence[str] | None = None,
        tenant_id: str | None = None,
        include_embeddings: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Synthesize context recall by querying the PostgreSQL ledger.
        Legacy-compatible wrapper for cognitive routes and context assembly.
        """
        _METRICS["recall_requests"] += 1

        if self._retrieval_adapter is not None:
            try:
                results = self._retrieval_adapter.retrieve(query, top_k=top_k)
                return {
                    "results": results,
                    "status": "ok",
                    "source": "adapter",
                }
            except Exception as exc:
                logger.debug("Retrieval adapter failed, falling back: %s", exc)

        self._ensure_db_session_factory()
        
        if not self._db_session_factory:
            return {"results": [], "status": "degraded", "reason": "database unavailable"}

        user_uuid = _coerce_uuid(user_id) if not isinstance(user_id, dict) else _coerce_uuid(user_id.get("user_id") or user_id.get("id"))
        tenant_uuid = _coerce_uuid(tenant_id) if tenant_id else None
        activation = decide_activation_mode(
            query=query or "",
            latency_budget_ms=int(kwargs.get("latency_budget_ms", 250) or 250),
            has_profile=bool(kwargs.get("has_profile", False)),
        )
        effective_top_k = min(max(int(top_k or 10), 1), max(int(activation.top_k), 1))
        
        async with self._db_session_factory() as session:
            # Simple lexical-ish fallback query on the ledger for now
            # Phase 8 will implement the full Hybrid Retrieval Router
            stmt = select(MemoryAssertion).where(MemoryAssertion.user_id == user_uuid)
            if tenant_uuid:
                stmt = stmt.where(MemoryAssertion.tenant_id == tenant_uuid)
            
            # Simple content filter if query provided
            if query and len(query) > 2:
                stmt = stmt.where(MemoryAssertion.content.ilike(f"%{query}%"))
                
            if activation.mode.value == "none":
                return {"results": [], "status": "success", "count": 0, "activation_mode": activation.mode.value}

            if activation.mode.value == "profile":
                stmt = stmt.where(MemoryAssertion.memory_class.in_(["profile", "semantic", "fact"]))
            elif activation.mode.value == "procedural":
                stmt = stmt.where(MemoryAssertion.memory_class.in_(["procedure", "tool_use", "workflow"]))

            stmt = stmt.order_by(MemoryAssertion.created_at.desc()).limit(effective_top_k)
            result = await session.execute(stmt)
            items = result.scalars().all()
            
            formatted = []
            for item in items:
                formatted.append({
                    "id": str(item.assertion_id),
                    "content": item.content,
                    "confidence": item.confidence,
                    "timestamp": item.created_at.timestamp(),
                    "memory_type": "assertion"
                })
                
            _METRICS["recall_hits"] += len(formatted)
            return {
                "results": formatted, 
                "status": "success", 
                "count": len(formatted),
                "activation_mode": activation.mode.value,
            }

    def _schedule_background(self, coro: Any) -> None:
        """Schedule a background task if an event loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running event loop; skipping background task scheduling.")
            return

        task = loop.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _hash_payload(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _hash_idempotency_key(
        self,
        tenant_id: str,
        user_id: str,
        source_type: str,
        source_ref: str | None,
        signal: MemorySignal,
    ) -> str:
        raw = "|".join(
            [
                tenant_id,
                user_id,
                source_type,
                source_ref or "",
                signal.signal_type,
                signal.text,
                signal.metadata.get("origin", ""),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def process_interaction(
        self,
        text: str,
        tenant_id: str,
        user_id: str,
        source_type: str = "chat",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Process an interaction, extract signals, and manage memory.
        """
        _METRICS["interactions_processed"] += 1
        self._ensure_db_session_factory()

        extraction_result = await self.signal_pipeline.process_text(
            text=text, tenant_id=tenant_id, user_id=user_id
        )
        _METRICS["signals_extracted"] += len(extraction_result.signals)

        admitted_signals: list[dict[str, Any]] = []
        for signal in extraction_result.signals:
            worthiness = await self.worthiness_scorer.evaluate(
                signal.text, signal.signal_type
            )

            if worthiness["is_worthy"]:
                admitted_signals.append({"signal": signal, "score": worthiness["score"]})
            else:
                logger.debug(
                    "Signal discarded (score %s < %s): %s",
                    worthiness["score"],
                    worthiness["threshold"],
                    signal.text[:80],
                )

        shadow_mode = self.flags.is_enabled(
            "memory_shadow_mode_enabled", tenant_id, user_id
        )
        learning_enabled = self.flags.is_enabled(
            "memory_learning_enabled", tenant_id, user_id
        )
        persist_enabled = bool(admitted_signals) and learning_enabled and not shadow_mode

        if persist_enabled:
            await self._commit_to_ledger(
                admitted_signals,
                tenant_id,
                user_id,
                source_type,
                source_ref,
                metadata=metadata,
            )
        elif admitted_signals:
            _METRICS["shadow_mode_runs"] += 1

        status = "success"
        if shadow_mode or not learning_enabled:
            status = "shadow"
        if extraction_result.status != "success" or (
            extraction_result.signals and not admitted_signals
        ):
            status = "degraded"
        if extraction_result.status == "failed":
            status = "failed"

        return {
            "extracted": len(extraction_result.signals),
            "admitted": len(admitted_signals),
            "persisted": len(admitted_signals) if persist_enabled else 0,
            "shadow_mode": shadow_mode,
            "learning_enabled": learning_enabled,
            "status": status,
            "errors": list(extraction_result.errors),
            "processing_time_ms": extraction_result.processing_time_ms,
        }

    async def _commit_to_ledger(
        self,
        admitted_signals: Sequence[dict[str, Any]],
        tenant_id: str,
        user_id: str,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write to Postgres ledger and enqueue projections."""
        if not self._db_session_factory:
            logger.warning("DB session factory not set. Cannot commit memory to ledger.")
            return

        tenant_uuid = _coerce_uuid(tenant_id)
        user_uuid = _coerce_uuid(user_id)
        committed_events: list[dict[str, Any]] = []

        async with self._db_session_factory() as session:
            for item in admitted_signals:
                signal: MemorySignal = item["signal"]
                score: float = float(item["score"])
                merged_metadata = dict(signal.metadata or {})
                if metadata:
                    merged_metadata.update(metadata)
                event_id = uuid.uuid4()
                payload_hash = self._hash_payload(signal.text)
                idempotency_key = self._hash_idempotency_key(
                    tenant_id, user_id, source_type, source_ref, signal
                )
                signal_payload = {
                    "text": signal.text,
                    "type": signal.signal_type,
                    "entities": _json_safe(signal.entities),
                    "keywords": _json_safe(signal.keywords),
                    "metadata": _json_safe(merged_metadata),
                }

                try:
                    event = MemoryEvent(
                        event_id=event_id,
                        tenant_id=tenant_uuid,
                        user_id=user_uuid,
                        source_type=source_type,
                        source_ref=source_ref or merged_metadata.get("source_ref"),
                        payload_hash=payload_hash,
                        idempotency_key=idempotency_key,
                        confidence=score,
                        scope=signal.scope,
                        sensitivity_class=str(merged_metadata.get("sensitivity_class", "normal")),
                        consent_state=str(merged_metadata.get("consent_state", "granted")),
                        event_type="signal_extracted",
                        payload=signal_payload,
                    )
                    session.add(event)

                    if signal.signal_type == "preference":
                        fact = ProfileFact(
                            event_id=event_id,
                            tenant_id=tenant_uuid,
                            user_id=user_uuid,
                            category="preference",
                            attribute=str(merged_metadata.get("attribute", "user_preference")),
                            value={
                                "text": signal.text,
                                "keywords": signal.keywords,
                                "entities": signal.entities,
                            },
                            confidence=score,
                            source_type=source_type,
                            source_ref=source_ref or merged_metadata.get("source_ref"),
                        )
                        session.add(fact)
                        derived_record = {
                            "kind": "profile_fact",
                            "profile_fact_id": str(fact.fact_id),
                        }
                    else:
                        assertion = MemoryAssertion(
                            event_id=event_id,
                            tenant_id=tenant_uuid,
                            user_id=user_uuid,
                            content=signal.text,
                            confidence=score,
                            scope=signal.scope,
                            sensitivity_class=str(
                                merged_metadata.get("sensitivity_class", "normal")
                            ),
                            consent_state=str(merged_metadata.get("consent_state", "granted")),
                            valid_from=_coerce_datetime(merged_metadata.get("valid_from")),
                            valid_to=_coerce_datetime(merged_metadata.get("valid_to")),
                            supersedes=(
                                _coerce_uuid(merged_metadata["supersedes"])
                                if merged_metadata.get("supersedes")
                                else None
                            ),
                        )
                        session.add(assertion)
                        derived_record = {
                            "kind": "memory_assertion",
                            "assertion_id": str(assertion.assertion_id),
                        }

                    if merged_metadata.get("reinforces"):
                        session.add(
                            ReinforcementEvent(
                                event_id=event_id,
                                target_assertion_id=_coerce_uuid(
                                    merged_metadata["reinforces"]
                                ),
                                weight=float(merged_metadata.get("reinforcement_weight", 0.1)),
                            )
                        )

                    if merged_metadata.get("contradicts"):
                        target_id = _coerce_uuid(merged_metadata["contradicts"])
                        session.add(
                            ContradictionEvent(
                                event_id=event_id,
                                source_assertion_id=target_id,
                                target_assertion_id=target_id,
                                resolution_status="open",
                            )
                        )

                    summary = merged_metadata.get("episode_summary") or signal.text[:160]
                    session.add(
                        MemoryEpisode(
                            event_id=event_id,
                            tenant_id=tenant_uuid,
                            user_id=user_uuid,
                            session_id=merged_metadata.get("session_id"),
                            summary=summary,
                            snapshot_data={
                                "event_id": str(event_id),
                                "signal_type": signal.signal_type,
                                "confidence": score,
                                "text": signal.text,
                                "metadata": _json_safe(merged_metadata),
                            },
                        )
                    )

                    stores = ["redis", "duckdb"]
                    if self.flags.is_enabled(
                        "graph_relationships_enabled", tenant_id, user_id
                    ):
                        stores.append("leangraph")

                    for store in stores:
                        session.add(
                            ProjectionStatus(
                                event_id=event_id,
                                target_store=store,
                                status="pending",
                            )
                        )

                    await session.commit()
                    _METRICS["ledger_writes"] += 1
                    _METRICS["signals_admitted"] += 1
                    committed_events.append(
                        {
                            "event": {
                                "event_id": str(event_id),
                                "tenant_id": str(tenant_uuid),
                                "user_id": str(user_uuid),
                                "source_type": source_type,
                                "source_ref": source_ref or merged_metadata.get("source_ref"),
                                "payload_hash": payload_hash,
                                "confidence": score,
                                "scope": signal.scope,
                                "sensitivity_class": merged_metadata.get(
                                    "sensitivity_class", "normal"
                                ),
                                "consent_state": merged_metadata.get(
                                    "consent_state", "granted"
                                ),
                                "session_id": merged_metadata.get("session_id"),
                                "created_at": event.created_at.isoformat()
                                if getattr(event, "created_at", None)
                                else None,
                                "payload": _json_safe(signal_payload),
                            },
                            "assertion": derived_record
                            if signal.signal_type != "preference"
                            else {
                                "event_id": str(event_id),
                                "profile_fact_id": derived_record["profile_fact_id"],
                                "content": signal.text,
                                "confidence": score,
                                "scope": signal.scope,
                            },
                        }
                    )
                except IntegrityError:
                    await session.rollback()
                    _METRICS["ledger_duplicates"] += 1
                    logger.info(
                        "Duplicate memory event skipped for tenant=%s user=%s source=%s",
                        tenant_id,
                        user_id,
                        source_type,
                    )
                except Exception as exc:
                    await session.rollback()
                    logger.exception("Failed to commit memory event: %s", exc)

        if committed_events:
            self._schedule_background(
                self._trigger_projections(committed_events, tenant_id, user_id)
            )

        if committed_events and self.flags.is_enabled(
            "profile_synthesis_enabled", tenant_id, user_id
        ):
            _METRICS["profile_synthesis_requests"] += 1
            self._schedule_background(
                self._trigger_profile_synthesis(committed_events, tenant_id, user_id)
            )

        if committed_events and self.flags.is_enabled("echocore_enabled", tenant_id, user_id):
            self._emit_echocore_candidates(committed_events)

    async def _update_projection_status(
        self,
        event_id: str,
        target_store: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        if not self._db_session_factory:
            return

        async with self._db_session_factory() as session:
            stmt = (
                select(ProjectionStatus)
                .where(ProjectionStatus.event_id == _coerce_uuid(event_id))
                .where(ProjectionStatus.target_store == target_store)
            )
            result = await session.execute(stmt)
            projection = result.scalar_one_or_none()
            if projection is None:
                return

            projection.status = status
            projection.last_error = last_error
            await session.commit()

    async def _trigger_projections(
        self,
        committed_events: Sequence[dict[str, Any]],
        tenant_id: str,
        user_id: str,
    ) -> None:
        """Fan out committed events to the specialized projection workers."""
        from .projections import get_projection_manager
        
        manager = get_projection_manager()
        for committed in committed_events:
            event_data = committed["event"]
            assertion_data = committed.get("assertion")
            event_id = event_data["event_id"]

            try:
                # Use the new projection manager for all configured stores
                await manager.project_event(event_data, assertion_data)
                _METRICS["projection_dispatches"] += 1
                
                # Update status for all stores handled by the manager
                # In a more advanced version, manager would return per-store success
                for store_name in ("redis", "leangraph", "duckdb"):
                    await self._update_projection_status(
                        event_id, store_name, "completed"
                    )
                    
            except Exception as exc:
                _METRICS["projection_failures"] += 1
                logger.warning(
                    "Projection orchestration failed for event %s: %s",
                    event_id,
                    exc,
                )

        logger.info(
            "Triggered asynchronous projections for %s committed memory events.",
            len(committed_events),
        )

    async def _trigger_profile_synthesis(
        self,
        committed_events: Sequence[dict[str, Any]],
        tenant_id: str,
        user_id: str,
    ) -> None:
        """Trigger synthesis of profile summary from durable facts."""
        logger.info(
            "Triggered profile synthesis update for tenant=%s user=%s (%s events).",
            tenant_id,
            user_id,
            len(committed_events),
        )

    def _emit_echocore_candidates(self, committed_events: Sequence[dict[str, Any]]) -> None:
        """Emit candidates for EchoCore offline consolidation."""
        _METRICS["echocore_candidates"] += len(committed_events)
        logger.info(
            "Emitted EchoCore archival candidates for %s events.",
            len(committed_events),
        )

    async def inspect_memory_state(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return a structured memory inspection snapshot for operators and users."""
        _METRICS["inspector_requests"] += 1
        self._ensure_db_session_factory()

        snapshot: dict[str, Any] = {
            "status": "degraded" if not self._db_session_factory else "success",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "limit": limit,
            "feature_flags": {
                "memory_learning_enabled": self.flags.is_enabled(
                    "memory_learning_enabled", tenant_id, user_id
                ),
                "memory_shadow_mode_enabled": self.flags.is_enabled(
                    "memory_shadow_mode_enabled", tenant_id, user_id
                ),
                "memory_inspector_enabled": self.flags.is_enabled(
                    "memory_inspector_enabled", tenant_id, user_id
                ),
                "memory_consent_controls_enabled": self.flags.is_enabled(
                    "memory_consent_controls_enabled", tenant_id, user_id
                ),
                "memory_retention_controls_enabled": self.flags.is_enabled(
                    "memory_retention_controls_enabled", tenant_id, user_id
                ),
                "memory_profile_corrections_enabled": self.flags.is_enabled(
                    "memory_profile_corrections_enabled", tenant_id, user_id
                ),
            },
            "metrics": get_metrics()["memory_runtime"],
            "recent_events": [],
            "recent_assertions": [],
            "recent_profile_facts": [],
            "recent_episodes": [],
            "open_contradictions": [],
            "consent_scopes": [],
            "retention_policies": [],
            "projection_status": [],
        }

        if not self._db_session_factory:
            return snapshot

        limit = max(1, min(int(limit), 100))

        tenant_uuid = _coerce_uuid(tenant_id) if tenant_id else None
        user_uuid = _coerce_uuid(user_id) if user_id else None

        async with self._db_session_factory() as session:
            event_filters: list[Any] = []
            assertion_filters: list[Any] = []
            fact_filters: list[Any] = []
            episode_filters: list[Any] = []
            consent_filters: list[Any] = []
            retention_filters: list[Any] = []
            if tenant_uuid is not None:
                event_filters.append(MemoryEvent.tenant_id == tenant_uuid)
                assertion_filters.append(MemoryAssertion.tenant_id == tenant_uuid)
                fact_filters.append(ProfileFact.tenant_id == tenant_uuid)
                episode_filters.append(MemoryEpisode.tenant_id == tenant_uuid)
                consent_filters.append(ConsentScope.tenant_id == tenant_uuid)
                retention_filters.append(RetentionPolicy.tenant_id == tenant_uuid)
            if user_uuid is not None:
                event_filters.append(MemoryEvent.user_id == user_uuid)
                assertion_filters.append(MemoryAssertion.user_id == user_uuid)
                fact_filters.append(ProfileFact.user_id == user_uuid)
                episode_filters.append(MemoryEpisode.user_id == user_uuid)
                consent_filters.append(ConsentScope.user_id == user_uuid)

            base_event_query = select(MemoryEvent)
            if event_filters:
                base_event_query = base_event_query.where(*event_filters)

            event_result = await session.execute(
                base_event_query.order_by(MemoryEvent.created_at.desc()).limit(limit)
            )
            events = event_result.scalars().all()

            assertion_query = select(MemoryAssertion)
            if assertion_filters:
                assertion_query = assertion_query.where(*assertion_filters)
            assertion_result = await session.execute(
                assertion_query.order_by(MemoryAssertion.created_at.desc()).limit(limit)
            )
            assertions = assertion_result.scalars().all()

            fact_query = select(ProfileFact)
            if fact_filters:
                fact_query = fact_query.where(*fact_filters)
            fact_result = await session.execute(
                fact_query.order_by(ProfileFact.created_at.desc()).limit(limit)
            )
            facts = fact_result.scalars().all()

            episode_query = select(MemoryEpisode)
            if episode_filters:
                episode_query = episode_query.where(*episode_filters)
            episode_result = await session.execute(
                episode_query.order_by(MemoryEpisode.created_at.desc()).limit(limit)
            )
            episodes = episode_result.scalars().all()

            contradiction_query = select(ContradictionEvent)
            if event_filters:
                contradiction_query = contradiction_query.join(
                    MemoryEvent,
                    MemoryEvent.event_id == ContradictionEvent.event_id,
                )
                if tenant_uuid is not None:
                    contradiction_query = contradiction_query.where(
                        MemoryEvent.tenant_id == tenant_uuid
                    )
                if user_uuid is not None:
                    contradiction_query = contradiction_query.where(
                        MemoryEvent.user_id == user_uuid
                    )
            contradiction_result = await session.execute(
                contradiction_query.order_by(ContradictionEvent.created_at.desc()).limit(limit)
            )
            contradictions = contradiction_result.scalars().all()

            consent_query = select(ConsentScope)
            if consent_filters:
                consent_query = consent_query.where(*consent_filters)
            consent_result = await session.execute(
                consent_query.order_by(ConsentScope.granted_at.desc()).limit(limit)
            )
            consents = consent_result.scalars().all()

            retention_query = select(RetentionPolicy)
            if tenant_uuid is not None:
                retention_query = retention_query.where(
                    (RetentionPolicy.tenant_id == tenant_uuid)
                    | (RetentionPolicy.tenant_id.is_(None))
                )
            elif retention_filters:
                retention_query = retention_query.where(*retention_filters)
            retention_result = await session.execute(
                retention_query.order_by(RetentionPolicy.updated_at.desc()).limit(limit)
            )
            retentions = retention_result.scalars().all()

            projection_query = select(ProjectionStatus)
            if event_filters:
                projection_query = projection_query.join(
                    MemoryEvent,
                    MemoryEvent.event_id == ProjectionStatus.event_id,
                )
                if tenant_uuid is not None:
                    projection_query = projection_query.where(
                        MemoryEvent.tenant_id == tenant_uuid
                    )
                if user_uuid is not None:
                    projection_query = projection_query.where(
                        MemoryEvent.user_id == user_uuid
                    )
            projection_result = await session.execute(
                projection_query.order_by(ProjectionStatus.updated_at.desc()).limit(limit)
            )
            projections = projection_result.scalars().all()

            def _serialize_datetime(value: Any) -> str | None:
                if value is None:
                    return None
                if isinstance(value, datetime):
                    return value.isoformat()
                return str(value)

            def _serialize_event(row: MemoryEvent) -> dict[str, Any]:
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
                    "valid_from": _serialize_datetime(row.valid_from),
                    "valid_to": _serialize_datetime(row.valid_to),
                    "supersedes": str(row.supersedes) if row.supersedes else None,
                    "event_type": row.event_type,
                    "created_at": _serialize_datetime(row.created_at),
                    "updated_at": _serialize_datetime(row.updated_at),
                    "payload": _json_safe(row.payload),
                }

            snapshot["recent_events"] = [_serialize_event(row) for row in events]
            snapshot["recent_assertions"] = [
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
                    "valid_from": _serialize_datetime(row.valid_from),
                    "valid_to": _serialize_datetime(row.valid_to),
                    "supersedes": str(row.supersedes) if row.supersedes else None,
                    "created_at": _serialize_datetime(row.created_at),
                    "updated_at": _serialize_datetime(row.updated_at),
                }
                for row in assertions
            ]
            snapshot["recent_profile_facts"] = [
                {
                    "fact_id": str(row.fact_id),
                    "event_id": str(row.event_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "category": row.category,
                    "attribute": row.attribute,
                    "value": _json_safe(row.value),
                    "confidence": row.confidence,
                    "source_type": row.source_type,
                    "source_ref": row.source_ref,
                    "valid_from": _serialize_datetime(row.valid_from),
                    "valid_to": _serialize_datetime(row.valid_to),
                    "supersedes": str(row.supersedes) if row.supersedes else None,
                    "created_at": _serialize_datetime(row.created_at),
                    "updated_at": _serialize_datetime(row.updated_at),
                }
                for row in facts
            ]
            snapshot["recent_episodes"] = [
                {
                    "episode_id": str(row.episode_id),
                    "event_id": str(row.event_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "session_id": row.session_id,
                    "summary": row.summary,
                    "snapshot_data": _json_safe(row.snapshot_data),
                    "created_at": _serialize_datetime(row.created_at),
                }
                for row in episodes
            ]
            snapshot["open_contradictions"] = [
                {
                    "contradiction_id": str(row.contradiction_id),
                    "event_id": str(row.event_id),
                    "source_assertion_id": str(row.source_assertion_id),
                    "target_assertion_id": str(row.target_assertion_id),
                    "resolution_status": row.resolution_status,
                    "created_at": _serialize_datetime(row.created_at),
                    "resolved_at": _serialize_datetime(row.resolved_at),
                }
                for row in contradictions
            ]
            snapshot["consent_scopes"] = [
                {
                    "scope_id": str(row.scope_id),
                    "tenant_id": str(row.tenant_id),
                    "user_id": str(row.user_id),
                    "scope_name": row.scope_name,
                    "is_granted": row.is_granted,
                    "granted_at": _serialize_datetime(row.granted_at),
                    "revoked_at": _serialize_datetime(row.revoked_at),
                }
                for row in consents
            ]
            snapshot["retention_policies"] = [
                {
                    "policy_id": str(row.policy_id),
                    "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                    "memory_class": row.memory_class,
                    "ttl_days": row.ttl_days,
                    "created_at": _serialize_datetime(row.created_at),
                    "updated_at": _serialize_datetime(row.updated_at),
                }
                for row in retentions
            ]
            snapshot["projection_status"] = [
                {
                    "projection_id": str(row.projection_id),
                    "event_id": str(row.event_id),
                    "target_store": row.target_store,
                    "status": row.status,
                    "retry_count": row.retry_count,
                    "last_error": row.last_error,
                    "created_at": _serialize_datetime(row.created_at),
                    "updated_at": _serialize_datetime(row.updated_at),
                }
                for row in projections
            ]

            counts = {}
            for name, model, filters in (
                ("events", MemoryEvent, event_filters),
                ("assertions", MemoryAssertion, assertion_filters),
                ("profile_facts", ProfileFact, fact_filters),
                ("episodes", MemoryEpisode, episode_filters),
                ("contradictions", ContradictionEvent, []),
                ("consent_scopes", ConsentScope, consent_filters),
                ("retention_policies", RetentionPolicy, retention_filters),
            ):
                count_stmt = select(func.count()).select_from(model)
                if model is ContradictionEvent:
                    count_stmt = count_stmt.join(
                        MemoryEvent,
                        MemoryEvent.event_id == ContradictionEvent.event_id,
                    )
                    if tenant_uuid is not None:
                        count_stmt = count_stmt.where(MemoryEvent.tenant_id == tenant_uuid)
                    if user_uuid is not None:
                        count_stmt = count_stmt.where(MemoryEvent.user_id == user_uuid)
                else:
                    if filters:
                        count_stmt = count_stmt.where(*filters)
                result = await session.execute(count_stmt)
                counts[name] = int(result.scalar_one() or 0)

            snapshot["counts"] = counts

        return snapshot

    async def list_consent_scopes(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Return consent scope rows for a tenant/user pair."""
        self._ensure_db_session_factory()
        if not self._db_session_factory:
            return {"status": "degraded", "items": []}

        tenant_uuid = _coerce_uuid(tenant_id)
        user_uuid = _coerce_uuid(user_id) if user_id else None

        async with self._db_session_factory() as session:
            query = select(ConsentScope).where(ConsentScope.tenant_id == tenant_uuid)
            if user_uuid is not None:
                query = query.where(ConsentScope.user_id == user_uuid)
            result = await session.execute(query.order_by(ConsentScope.granted_at.desc()))
            items = result.scalars().all()
            return {
                "status": "success",
                "items": [
                    {
                        "scope_id": str(row.scope_id),
                        "tenant_id": str(row.tenant_id),
                        "user_id": str(row.user_id),
                        "scope_name": row.scope_name,
                        "is_granted": row.is_granted,
                        "granted_at": row.granted_at.isoformat()
                        if row.granted_at
                        else None,
                        "revoked_at": row.revoked_at.isoformat()
                        if row.revoked_at
                        else None,
                    }
                    for row in items
                ],
            }

    async def set_consent_scope(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope_name: str,
        granted: bool,
    ) -> dict[str, Any]:
        """Create or update a consent scope entry."""
        _METRICS["consent_updates"] += 1
        self._ensure_db_session_factory()
        if not self._db_session_factory:
            return {"status": "degraded", "granted": granted}

        tenant_uuid = _coerce_uuid(tenant_id)
        user_uuid = _coerce_uuid(user_id)
        now = datetime.utcnow()

        async with self._db_session_factory() as session:
            query = select(ConsentScope).where(
                ConsentScope.tenant_id == tenant_uuid,
                ConsentScope.user_id == user_uuid,
                ConsentScope.scope_name == scope_name,
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            if row is None:
                row = ConsentScope(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    scope_name=scope_name,
                    is_granted=granted,
                    granted_at=now,
                    revoked_at=None if granted else now,
                )
                session.add(row)
            else:
                row.is_granted = granted
                row.revoked_at = None if granted else now
                if granted and row.granted_at is None:
                    row.granted_at = now
            await session.commit()
            return {
                "status": "success",
                "scope_id": str(row.scope_id),
                "tenant_id": str(row.tenant_id),
                "user_id": str(row.user_id),
                "scope_name": row.scope_name,
                "is_granted": row.is_granted,
                "granted_at": row.granted_at.isoformat() if row.granted_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }

    async def list_retention_policies(
        self,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Return retention policy rows for a tenant or global scope."""
        self._ensure_db_session_factory()
        if not self._db_session_factory:
            return {"status": "degraded", "items": []}

        tenant_uuid = _coerce_uuid(tenant_id) if tenant_id else None
        async with self._db_session_factory() as session:
            query = select(RetentionPolicy)
            if tenant_uuid is not None:
                query = query.where(
                    (RetentionPolicy.tenant_id == tenant_uuid)
                    | (RetentionPolicy.tenant_id.is_(None))
                )
            result = await session.execute(query.order_by(RetentionPolicy.updated_at.desc()))
            items = result.scalars().all()
            return {
                "status": "success",
                "items": [
                    {
                        "policy_id": str(row.policy_id),
                        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                        "memory_class": row.memory_class,
                        "ttl_days": row.ttl_days,
                        "created_at": row.created_at.isoformat()
                        if row.created_at
                        else None,
                        "updated_at": row.updated_at.isoformat()
                        if row.updated_at
                        else None,
                    }
                    for row in items
                ],
            }

    async def set_retention_policy(
        self,
        *,
        memory_class: str,
        ttl_days: int | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a retention policy entry."""
        _METRICS["retention_updates"] += 1
        self._ensure_db_session_factory()
        if not self._db_session_factory:
            return {"status": "degraded", "ttl_days": ttl_days}

        tenant_uuid = _coerce_uuid(tenant_id) if tenant_id else None

        async with self._db_session_factory() as session:
            query = select(RetentionPolicy).where(
                RetentionPolicy.memory_class == memory_class,
                RetentionPolicy.tenant_id.is_(None)
                if tenant_uuid is None
                else RetentionPolicy.tenant_id == tenant_uuid,
            )
            result = await session.execute(query)
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
            return {
                "status": "success",
                "policy_id": str(row.policy_id),
                "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                "memory_class": row.memory_class,
                "ttl_days": row.ttl_days,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

    def set_shadow_mode(
        self,
        *,
        enabled: bool,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Set the active memory shadow-mode gate."""
        if tenant_id:
            self.flags.set_tenant_override(tenant_id, "memory_shadow_mode_enabled", enabled)
        elif user_id:
            self.flags.set_user_override(user_id, "memory_shadow_mode_enabled", enabled)
        else:
            self.flags.set_global("memory_shadow_mode_enabled", enabled)

        return {
            "status": "success",
            "enabled": enabled,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "effective": self.flags.is_enabled(
                "memory_shadow_mode_enabled", tenant_id, user_id
            ),
        }

    async def close(self) -> None:
        """Cancel any pending background tasks."""
        if not self._background_tasks:
            return

        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()

        with suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)

        self._background_tasks.clear()


memory_manager = MemoryRuntimeManager()


def get_memory_manager() -> MemoryRuntimeManager:
    return memory_manager


def init_memory() -> MemoryRuntimeManager:
    """Compatibility initializer used by startup code."""
    logger.info("Initializing memory runtime manager")
    repo_src = Path(__file__).resolve().parents[3] / "ai_karen_engine"
    for py_file in repo_src.rglob("*.py"):
        if "core/neuro_vault" in str(py_file):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if "core.neuro_vault" in text or "from ai_karen_engine.core.neuro_vault" in text:
            logger.warning(
                "memory.neuro_vault_runtime_import_detected",
                extra={
                    "module": str(py_file.relative_to(repo_src)),
                    "import_path": "ai_karen_engine.core.neuro_vault",
                    "severity": "warning",
                    "replacement": "ai_karen_engine.core.memory",
                    "correlation_id": "startup-memory-audit",
                },
            )
    memory_manager._ensure_db_session_factory()
    return memory_manager


async def close() -> None:
    """Compatibility shutdown hook used by startup cleanup."""
    await memory_manager.close()


async def recall_context(
    *,
    user_id: Any,
    tenant_id: str,
    query: str,
    conversation_id: str | None = None,
    session_id: str | None = None,
    top_k: int = 10,
    correlation_id: str | None = None,
    activation: Any | None = None,
    tiers: Sequence[str] | None = None,
    include_embeddings: bool = False,
    **kwargs,
) -> dict[str, Any]:
    """
    Compatibility recall API used by cognitive routes and UI helpers.

    Falls back to an empty result if the database memory manager is unavailable.
    """
    _METRICS["recall_requests"] += 1

    try:
        effective_top_k = int(kwargs.get("limit", top_k) or top_k)
        user_ctx = user_id if isinstance(user_id, dict) else kwargs.get("user_ctx")
        if isinstance(user_ctx, dict):
            user_id = user_ctx.get("user_id") or user_ctx.get("id") or user_id

        if not tenant_id:
            raise ValueError("tenant_id is required for memory recall; refusing default tenant fallback")

        from .retrieval.retrieval_router import get_retrieval_router
        from .types import MemoryQuery

        # Build unified query model
        query_model = MemoryQuery(
            text=str(query or ""),
            user_id=str(user_id) if user_id is not None else None,
            tenant_id=str(tenant_id),
            top_k=effective_top_k
        )
        
        # Phase 8: Use Hybrid Retrieval Router across all projection stores
        router = get_retrieval_router()
        items = await router.recall(query_model)
        
        formatted: list[dict[str, Any]] = []
        for item in items:
            formatted.append({
                "id": item.id,
                "content": item.content,
                "metadata": item.to_dict().get("metadata", {}),
                "timestamp": item.timestamp.timestamp(),
                "similarity_score": item.relevance,
                "memory_type": item.memory_type.value,
                "result": item.content
            })
            
        _METRICS["recall_hits"] += len(formatted)
        return {"results": formatted, "status": "success", "count": len(formatted)}
    except Exception as exc:
        logger.warning("Recall failed for user=%s query=%r: %s", user_id, query, exc)
        return {"results": [], "status": "degraded", "error": str(exc)}


async def update_memory(
    memory_id: str,
    updates: dict[str, Any],
    user_ctx: dict[str, Any] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """
    Compatibility update API.

    The new runtime manager treats updates as a fresh signal when a direct
    mutation path is not available.
    """
    content = updates.get("content") or updates.get("text") or updates.get("query") or ""
    if not content:
        return {"status": "noop", "memory_id": memory_id, "updated": False}

    tenant_id = str((user_ctx or {}).get("tenant_id") or kwargs.get("tenant_id") or "")
    if not tenant_id:
        return {
            "status": "rejected",
            "memory_id": memory_id,
            "updated": False,
            "reason": "missing_tenant_id",
        }
    user_id = str(
        (user_ctx or {}).get("user_id")
        or kwargs.get("user_id")
        or "anonymous"
    )

    result = await memory_manager.process_interaction(
        text=str(content),
        tenant_id=tenant_id,
        user_id=user_id,
        source_type=str(updates.get("source_type", "manual_update")),
        source_ref=str(updates.get("source_ref") or memory_id),
        metadata=updates.get("metadata")
        if isinstance(updates.get("metadata"), dict)
        else None,
    )
    result["memory_id"] = memory_id
    result["updated"] = True
    return result


async def export_promoted_artifacts(*, limit: int = 100, **kwargs) -> dict[str, Any]:
    """
    Compatibility export hook for offline consolidation pipelines.

    Returns a preview of durable memory candidates suitable for EchoCore or
    operator review.
    """
    limit = max(1, min(int(limit), 500))
    tenant_id = kwargs.get("tenant_id")
    user_id = kwargs.get("user_id")

    try:
        inspection = await memory_manager.inspect_memory_state(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
        )
        artifacts: list[dict[str, Any]] = []

        for row in inspection.get("recent_profile_facts", [])[:limit]:
            artifacts.append(
                {
                    "artifact_id": row.get("fact_id"),
                    "artifact_type": "user_preference"
                    if row.get("category") == "preference"
                    else "long_term_fact",
                    "source_tier": "ltm",
                    "user_id": row.get("user_id"),
                    "tenant_id": row.get("tenant_id"),
                    "session_id": row.get("event_id"),
                    "thread_id": None,
                    "content": {
                        "category": row.get("category"),
                        "attribute": row.get("attribute"),
                        "value": row.get("value"),
                        "confidence": row.get("confidence"),
                    },
                    "importance_score": float(row.get("confidence") or 0.0),
                    "retention_score": 1.0,
                    "privacy_tags": [row.get("sensitivity_class", "normal")],
                    "training_eligibility": "review",
                    "metadata": {
                        "source": "profile_fact",
                        "source_ref": row.get("source_ref"),
                        "valid_from": row.get("valid_from"),
                        "valid_to": row.get("valid_to"),
                    },
                }
            )

        for row in inspection.get("recent_assertions", [])[:limit]:
            if len(artifacts) >= limit:
                break
            artifacts.append(
                {
                    "artifact_id": row.get("assertion_id"),
                    "artifact_type": "long_term_fact",
                    "source_tier": "ltm",
                    "user_id": row.get("user_id"),
                    "tenant_id": row.get("tenant_id"),
                    "session_id": row.get("event_id"),
                    "thread_id": None,
                    "content": {
                        "content": row.get("content"),
                        "scope": row.get("scope"),
                        "confidence": row.get("confidence"),
                    },
                    "importance_score": float(row.get("confidence") or 0.0),
                    "retention_score": 1.0,
                    "privacy_tags": [row.get("sensitivity_class", "normal")],
                    "training_eligibility": "review",
                    "metadata": {
                        "source": "memory_assertion",
                        "valid_from": row.get("valid_from"),
                        "valid_to": row.get("valid_to"),
                        "consent_state": row.get("consent_state"),
                    },
                }
            )

        return {
            "status": inspection.get("status", "success"),
            "count": len(artifacts),
            "limit": limit,
            "artifacts": artifacts,
        }
    except Exception as exc:
        logger.warning("Promoted artifact export failed: %s", exc)
        return {
            "status": "degraded",
            "count": 0,
            "limit": limit,
            "artifacts": [],
            "error": str(exc),
        }


def get_metrics() -> dict[str, Any]:
    """Return runtime and compatibility metrics."""
    from ..runtime.resilience import get_resilience_health_monitor

    return {
        "memory_runtime": dict(_METRICS),
        "memory_learning_enabled": memory_manager.flags.is_enabled(
            "memory_learning_enabled"
        ),
        "resilience_health": get_resilience_health_monitor().get_health_status(),
    }
