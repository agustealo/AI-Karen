"""Canonical memory formation pipeline.

Transforms runtime observations into worthy memory candidates, then delegates
all durable mutation authority to NeuroVault. Derived projections happen only
after a successful governed commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Protocol

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.protocols import VaultContext, VaultPort
from ai_karen_engine.core.memory.scoring import MemoryWorthinessScorer
from ai_karen_engine.core.memory.signals import MemorySignal, get_signal_pipeline
from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryType,
)

logger = get_logger(__name__)


class DerivedProjector(Protocol):
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
    ) -> dict[str, bool]: ...


class MemoryFormationService:
    """Form and persist governed durable memory from runtime observations."""

    def __init__(
        self,
        *,
        vault_factory: Callable[[str], VaultPort],
        derived_projector: DerivedProjector,
    ) -> None:
        self.signal_pipeline = get_signal_pipeline()
        self.worthiness_scorer = MemoryWorthinessScorer()
        self._vault_factory = vault_factory
        self._derived_projector = derived_projector

    async def process_interaction(
        self,
        *,
        text: str,
        tenant_id: str,
        user_id: str,
        source_type: str = "chat",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        policy_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_text = str(text or "").strip()
        tenant_id = str(tenant_id or "").strip()
        user_id = str(user_id or "").strip()
        if not normalized_text:
            return {
                "status": "noop",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "empty_interaction",
            }
        if not tenant_id or not user_id:
            return {
                "status": "rejected",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "missing_tenant_or_user_scope",
            }

        request_id = str(request_id or uuid.uuid4())
        correlation_id = str(correlation_id or uuid.uuid4())
        merged_metadata = self._json_safe(dict(metadata or {}))
        if session_id:
            merged_metadata.setdefault("session_id", session_id)
        if conversation_id:
            merged_metadata.setdefault("conversation_id", conversation_id)

        extraction = await self.signal_pipeline.process_text(
            text=normalized_text,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        admitted: list[tuple[MemorySignal, float]] = []
        for signal in extraction.signals:
            worthiness = await self.worthiness_scorer.evaluate(
                signal.text,
                signal.signal_type,
            )
            if worthiness.get("is_worthy"):
                admitted.append((signal, float(worthiness.get("score") or 0.0)))

        if not admitted:
            return {
                "status": "degraded" if extraction.status != "success" else "success",
                "extracted": len(extraction.signals),
                "admitted": 0,
                "persisted": 0,
                "errors": list(extraction.errors),
                "processing_time_ms": extraction.processing_time_ms,
            }

        context = VaultContext(
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            session_id=session_id,
            conversation_id=conversation_id,
            policy_context=dict(policy_context or {}),
        )

        persisted = 0
        persistence_failures = 0
        projection_failures = 0
        receipts: list[dict[str, Any]] = []
        errors: list[str] = list(extraction.errors)
        authorization_error: str | None = None
        vault = self._vault_factory(tenant_id)

        for signal, score in admitted:
            entry = self._entry_from_signal(
                signal=signal,
                score=score,
                tenant_id=tenant_id,
                user_id=user_id,
                source_type=source_type,
                source_ref=source_ref,
                metadata=merged_metadata,
                session_id=session_id,
                conversation_id=conversation_id,
            )
            try:
                receipt = await vault.persist(entry, context=context)
            except PermissionError as exc:
                authorization_error = str(exc)
                logger.warning(
                    "memory.formation.write_rejected",
                    extra={
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "reason": type(exc).__name__,
                    },
                )
                break
            except Exception as exc:
                persistence_failures += 1
                errors.append(f"persist:{type(exc).__name__}")
                logger.exception(
                    "memory.formation.persist_failed",
                    extra={
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "error_type": type(exc).__name__,
                    },
                )
                continue

            if not receipt.persisted:
                persistence_failures += 1
                errors.append("persist:not_persisted")
                continue

            persisted += 1
            event_id = str(receipt.metadata.get("event_id") or "")
            projection_results: dict[str, bool] = {}
            if event_id:
                try:
                    projection_results = await self._derived_projector.project(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        event_id=event_id,
                        memory_id=receipt.memory_id,
                        signal=signal,
                        confidence=score,
                        source_type=source_type,
                        source_ref=source_ref,
                        metadata=merged_metadata,
                    )
                except Exception as exc:
                    projection_failures += 1
                    errors.append(f"projection:{type(exc).__name__}")
                    logger.exception(
                        "memory.formation.projection_failed",
                        extra={
                            "tenant_id": tenant_id,
                            "user_id": user_id,
                            "event_id": event_id,
                            "memory_id": receipt.memory_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                    projection_results = {"projection_pipeline": False}
                else:
                    projection_failures += sum(
                        1 for ok in projection_results.values() if not ok
                    )

            receipts.append(
                {
                    "memory_id": receipt.memory_id,
                    "event_id": event_id or None,
                    "version": receipt.version,
                    "projection_results": projection_results,
                }
            )

        if authorization_error:
            return {
                "status": "rejected",
                "extracted": len(extraction.signals),
                "admitted": len(admitted),
                "persisted": persisted,
                "persistence_failures": persistence_failures,
                "projection_failures": projection_failures,
                "reason": "memory_write_not_authorized",
                "authorization_error": authorization_error,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "receipts": receipts,
                "errors": errors,
            }

        status = "success"
        if projection_failures or persistence_failures or extraction.status != "success":
            status = "degraded"
        if persisted == 0 and persistence_failures:
            status = "failed"
        if extraction.status == "failed" and persisted == 0:
            status = "failed"

        return {
            "status": status,
            "extracted": len(extraction.signals),
            "admitted": len(admitted),
            "persisted": persisted,
            "persistence_failures": persistence_failures,
            "projection_failures": projection_failures,
            "errors": errors,
            "processing_time_ms": extraction.processing_time_ms,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "receipts": receipts,
        }

    @staticmethod
    def _entry_from_signal(
        *,
        signal: MemorySignal,
        score: float,
        tenant_id: str,
        user_id: str,
        source_type: str,
        source_ref: str | None,
        metadata: dict[str, Any],
        session_id: str | None,
        conversation_id: str | None,
    ) -> MemoryEntry:
        memory_type = MemoryFormationService._memory_type(signal.signal_type)
        custom = MemoryFormationService._json_safe(dict(signal.metadata or {}))
        custom.update(MemoryFormationService._json_safe(metadata))
        custom.update(
            {
                "source_type": source_type,
                "source_ref": source_ref,
                "scope": signal.scope,
                "signal_type": signal.signal_type,
                "entities": MemoryFormationService._json_safe(list(signal.entities or [])),
                "keywords": MemoryFormationService._json_safe(list(signal.keywords or [])),
            }
        )
        return MemoryEntry(
            id=str(uuid.uuid4()),
            content=signal.text,
            memory_type=memory_type,
            namespace=MemoryNamespace.LONG_TERM,
            confidence=max(0.0, min(1.0, score)),
            importance=max(1.0, min(10.0, 1.0 + score * 9.0)),
            keywords=[str(keyword) for keyword in signal.keywords or []],
            entities=[
                str(entity.get("text") or entity.get("name") or "")
                for entity in signal.entities or []
                if str(entity.get("text") or entity.get("name") or "").strip()
            ],
            metadata=MemoryMetadata(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                session_id=session_id,
                source=source_type,
                custom=custom,
            ),
        )

    @staticmethod
    def _memory_type(signal_type: str) -> MemoryType:
        kind = str(signal_type or "").casefold()
        if kind in {"workflow", "procedure", "tool_use"}:
            return MemoryType.PROCEDURAL
        if kind in {"preference", "fact", "entity"}:
            return MemoryType.SEMANTIC
        return MemoryType.EPISODIC

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): MemoryFormationService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [MemoryFormationService._json_safe(item) for item in value]
        if isinstance(value, (datetime, date, uuid.UUID)):
            return value.isoformat() if hasattr(value, "isoformat") else str(value)
        if isinstance(value, Enum):
            return MemoryFormationService._json_safe(value.value)
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)


__all__ = ["MemoryFormationService"]
