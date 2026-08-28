from __future__ import annotations

"""Runtime-owned governed evidence resolution.

CORTEX states what evidence it needs. RuntimePolicy authorizes access. This
resolver performs the authorized retrieval exactly once and returns the same
typed ``CognitiveContext`` that CORTEX Stage 2 and ChatRuntime consume.

Memory retrieval is delegated exclusively to ``MemoryRuntimeManager`` which in
turn delegates selection/ranking to NeuroRecall. No compatibility memory service
or second retrieval authority is used here.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirement,
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from src.ai_karen_engine.platform.observability import get_observability_emitter
from src.ai_karen_engine.platform.observability.contracts import EventType as RuntimeEventType

logger = get_logger(__name__)


class RuntimeEvidenceResolver:
    """Resolve RuntimePolicy-authorized evidence into one typed context truth."""

    RESOLVER_ID = "runtime.evidence.memory"
    RESOLVER_VERSION = "1"

    def __init__(self, *, memory_manager: Any | None = None) -> None:
        self._memory_manager = memory_manager
        self._emitter = get_observability_emitter()

    async def resolve(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
    ) -> CognitiveContext:
        """Resolve every currently authorized source exactly once.

        Unsupported authorized sources remain in ``unresolved_sources``. A source
        is removed from that list only after its resolver actually completed,
        including a successful empty result set.
        """
        authorized = set(cognitive_context.authorized_sources)
        for requirement in cognitive_context.requirements.requirements:
            if requirement.source.value not in authorized:
                continue
            if requirement.source is EvidenceSource.MEMORY:
                await self._resolve_memory(request, cognitive_context, requirement)
        return cognitive_context

    async def _resolve_memory(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
        requirement: ContextRequirement,
    ) -> None:
        ctx = request.context
        self._emitter.emit(
            RuntimeEventType.MEMORY_RECALL_STARTED,
            policy_decision_id=cognitive_context.policy_decision_id,
            metadata={
                "context_id": cognitive_context.context_id,
                "resolver_id": self.RESOLVER_ID,
            },
        )

        try:
            memory_manager = self._memory_manager or self._get_memory_manager()
            result = await memory_manager.recall_context(
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                query=self._latest_user_message(request),
                top_k=max(0, int(requirement.max_items or 0)),
                tiers=tuple(requirement.classes),
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                correlation_id=ctx.correlation_id,
                request_id=ctx.request_id,
            )
        except Exception as exc:
            logger.warning(
                "Runtime evidence memory resolution failed: %s",
                exc,
                extra={
                    "correlation_id": ctx.correlation_id,
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                },
            )
            cognitive_context.metadata.update(
                {
                    "memory_recall_status": "failed",
                    "memory_recall_count": 0,
                    "memory_latency_ms": 0.0,
                    "memory_degraded": True,
                    "memory_degradation_reason": str(exc),
                    "memory_resolver_id": self.RESOLVER_ID,
                }
            )
            self._emitter.emit(
                RuntimeEventType.MEMORY_RECALL_COMPLETED,
                policy_decision_id=cognitive_context.policy_decision_id,
                memory_recall_count=0,
                metadata={
                    "context_id": cognitive_context.context_id,
                    "resolver_id": self.RESOLVER_ID,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return

        now = datetime.now(timezone.utc)
        raw_items = list(result.get("results") or [])
        max_items = max(0, int(requirement.max_items or 0))
        if max_items:
            raw_items = raw_items[:max_items]

        resolved = [
            self._memory_item_to_evidence(
                item,
                request=request,
                retrieved_at=now,
            )
            for item in raw_items
        ]
        cognitive_context.evidence.extend(resolved)
        self._mark_resolved(cognitive_context, EvidenceSource.MEMORY)

        degraded = bool(result.get("degraded")) or result.get("status") == "degraded"
        degradation_reason = result.get("degradation_reason") or result.get("reason")
        cognitive_context.metadata.update(
            {
                "memory_recall_status": result.get("status", "success"),
                "memory_recall_count": len(resolved),
                "memory_latency_ms": float(result.get("latency_ms") or 0.0),
                "memory_degraded": degraded,
                "memory_degradation_reason": degradation_reason,
                "memory_resolver_id": self.RESOLVER_ID,
                "memory_response_source": result.get("source", "neuro_recall"),
                "memory_provenance": tuple(result.get("provenance") or ()),
            }
        )
        self._emitter.emit(
            RuntimeEventType.MEMORY_RECALL_COMPLETED,
            policy_decision_id=cognitive_context.policy_decision_id,
            memory_recall_count=len(resolved),
            metadata={
                "context_id": cognitive_context.context_id,
                "resolver_id": self.RESOLVER_ID,
                "status": cognitive_context.metadata["memory_recall_status"],
                "degraded": degraded,
            },
        )

    @classmethod
    def _memory_item_to_evidence(
        cls,
        item: dict[str, Any],
        *,
        request: ChatExecutionRequest,
        retrieved_at: datetime,
    ) -> ContextEvidence:
        ctx = request.context
        item_metadata = dict(item.get("metadata") or {})
        evidence_id = str(item.get("id") or item_metadata.get("id") or "memory")
        timestamp = cls._coerce_datetime(item.get("timestamp"))
        contradiction = cls._contradiction_from_metadata(item_metadata)

        return ContextEvidence(
            evidence_id=evidence_id,
            source=EvidenceSource.MEMORY,
            content=str(item.get("content") or item.get("result") or ""),
            source_ref=evidence_id,
            relevance=cls._coerce_float(item.get("similarity_score")),
            confidence=cls._coerce_float(item_metadata.get("confidence")),
            provenance=EvidenceProvenance(
                source_ref=evidence_id,
                source_record_id=evidence_id,
                resolver_id=cls.RESOLVER_ID,
                resolver_version=cls.RESOLVER_VERSION,
                retrieval_method="neuro_recall",
                retrieved_at=retrieved_at,
                reason_codes=("memory_recall",),
            ),
            temporal=EvidenceTemporalContext(
                observed_at=timestamp,
                as_of=retrieved_at,
            ),
            contradiction=contradiction,
            scope=EvidenceScope(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
            ),
            metadata={
                "memory_type": item.get("memory_type"),
                "memory_metadata": item_metadata,
            },
        )

    @staticmethod
    def _mark_resolved(
        cognitive_context: CognitiveContext,
        source: EvidenceSource,
    ) -> None:
        cognitive_context.unresolved_sources = [
            value
            for value in cognitive_context.unresolved_sources
            if value != source.value
        ]

    @staticmethod
    def _latest_user_message(request: ChatExecutionRequest) -> str:
        for message in reversed(request.messages):
            if str(message.get("role", "")).lower() == "user":
                return str(message.get("content", ""))
        if request.messages:
            return str(request.messages[-1].get("content", ""))
        return ""

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _contradiction_from_metadata(
        metadata: dict[str, Any],
    ) -> EvidenceContradiction:
        raw_status = str(metadata.get("contradiction_status") or "unknown").lower()
        try:
            status = EvidenceContradictionStatus(raw_status)
        except ValueError:
            status = EvidenceContradictionStatus.UNKNOWN

        conflicting_ids = metadata.get("conflicting_evidence_ids") or ()
        if isinstance(conflicting_ids, str):
            conflicting_ids = (conflicting_ids,)

        reason_codes = metadata.get("contradiction_reason_codes") or ()
        if isinstance(reason_codes, str):
            reason_codes = (reason_codes,)

        return EvidenceContradiction(
            status=status,
            conflicting_evidence_ids=tuple(str(value) for value in conflicting_ids),
            reason_codes=tuple(str(value) for value in reason_codes),
            resolution_ref=(
                str(metadata["contradiction_resolution_ref"])
                if metadata.get("contradiction_resolution_ref") is not None
                else None
            ),
        )

    @staticmethod
    def _get_memory_manager() -> Any:
        from ai_karen_engine.core.memory import get_memory_manager

        return get_memory_manager()


__all__ = ["RuntimeEvidenceResolver"]
