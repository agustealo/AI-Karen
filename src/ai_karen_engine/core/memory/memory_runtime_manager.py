"""Canonical memory runtime manager.

Runtime owns execution and dependency composition. NeuroRecall owns recall
selection. MemoryFormationService turns runtime observations into candidates,
NeuroVault is the only durable mutation boundary, and MemoryControlService owns
operator/governance access. Core services receive backend-neutral contracts;
platform implementations are wired here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai_karen_engine.core.logging import get_logger

from . import _memory_runtime_base as _base
from .control import MemoryControlService
from .episodic import EventSegmenter
from .formation import MemoryFormationService
from .retrieval.neuro_recall import NeuroRecall, RecallRequest, RecallScopeError

logger = get_logger(__name__)


class MemoryRuntimeManager(_base.MemoryRuntimeManager):
    """Canonical memory execution and dependency-composition authority."""

    def __init__(
        self,
        retrieval_adapter: Any | None = None,
        consolidation_adapter: Any | None = None,
        recall_service: Any | None = None,
        formation_service: MemoryFormationService | None = None,
        control_service: MemoryControlService | None = None,
        stm: Any | None = None,
    ) -> None:
        if retrieval_adapter is not None:
            logger.warning(
                "memory.retrieval_adapter_ignored",
                extra={"replacement": "NeuroRecall"},
            )
        super().__init__(consolidation_adapter=consolidation_adapter)

        needs_default_stm = recall_service is None or formation_service is None
        self._stm = stm or (self._build_stm() if needs_default_stm else None)
        self._neuro_recall = recall_service or self._build_neuro_recall(self._stm)
        self._formation_service = formation_service or self._build_formation_service(
            self._stm
        )
        self._control_service = control_service or self._build_control_service()

    @property
    def control_service(self) -> MemoryControlService:
        return self._control_service

    @staticmethod
    def _build_stm() -> Any:
        """Build the one bounded-memory adapter shared by recall and formation."""
        from ai_karen_engine.platform.memory.redis import RedisSTMAdapter

        return RedisSTMAdapter()

    @staticmethod
    def _build_neuro_recall(stm: Any) -> NeuroRecall:
        """Compose concrete candidate sources beneath the one recall authority."""
        if stm is None:
            raise RuntimeError("STM adapter is required to compose NeuroRecall")

        from ai_karen_engine.platform.memory.postgres import (
            PostgresProfileRecallRetriever,
            PostgresProceduralRecallRetriever,
            PostgresRecallRetriever,
        )
        from ai_karen_engine.platform.memory.postgres.entity_resolver import (
            PostgresEntityResolver,
        )
        from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource

        from .graph.service import get_leangraph_service
        from .retrieval.retrieval_router import HybridRetrievalRouter

        source_router = HybridRetrievalRouter(
            stm=stm,
            graph=get_leangraph_service(),
            event_source=PostgresEventSource(),
            entity_resolver=PostgresEntityResolver(),
        )
        return NeuroRecall(
            retrievers=(
                PostgresRecallRetriever(),
                PostgresProfileRecallRetriever(),
                PostgresProceduralRecallRetriever(),
                source_router,
            )
        )

    @staticmethod
    def _build_formation_service(stm: Any) -> MemoryFormationService:
        """Compose governed durable writes, STM, and rebuildable projections."""
        if stm is None:
            raise RuntimeError("STM adapter is required to compose memory formation")

        from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
        from ai_karen_engine.platform.memory.postgres.derived_projector import (
            PostgresDerivedMemoryProjector,
        )
        from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault

        from .projections import HotStateWorker, MemoryGraphWorker, ProjectionManager

        projection_manager = ProjectionManager(
            {
                "stm": HotStateWorker(stm),
                "memory_graph": MemoryGraphWorker(),
            }
        )

        def vault_factory(tenant_id: str) -> PostgresNeuroVault:
            return PostgresNeuroVault(
                session_factory=lambda: async_transaction_scope(tenant_id=tenant_id)
            )

        return MemoryFormationService(
            vault_factory=vault_factory,
            derived_projector=PostgresDerivedMemoryProjector(projection_manager),
            episode_state_store=stm,
            event_segmenter=EventSegmenter(),
        )

    @staticmethod
    def _build_control_service() -> MemoryControlService:
        """Compose governed operator/control access over canonical PostgreSQL."""
        from ai_karen_engine.platform.memory.postgres import (
            PostgresMemoryControlRepository,
        )

        return MemoryControlService(PostgresMemoryControlRepository())

    def set_recall_service(self, service: Any) -> None:
        if service is None or not hasattr(service, "recall"):
            raise TypeError("recall service must provide async recall(request)")
        self._neuro_recall = service

    def set_formation_service(self, service: MemoryFormationService) -> None:
        if service is None or not hasattr(service, "process_interaction"):
            raise TypeError("formation service must provide async process_interaction(...)")
        self._formation_service = service

    def set_control_service(self, service: MemoryControlService) -> None:
        if service is None or not hasattr(service, "inspect_memory_state"):
            raise TypeError("control service must provide memory control operations")
        self._control_service = service

    async def _commit_to_ledger(self, *args: Any, **kwargs: Any) -> None:
        """Reject the retired direct-ledger mutation path."""
        del args, kwargs
        raise RuntimeError(
            "direct memory ledger writes are retired; use MemoryFormationService/NeuroVault"
        )

    async def process_interaction(
        self,
        text: str,
        tenant_id: str,
        user_id: str,
        source_type: str = "chat",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        policy_context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Process observations through the one governed durable-write path."""
        shadow_mode = self.flags.is_enabled(
            "memory_shadow_mode_enabled", tenant_id, user_id
        )
        learning_enabled = self.flags.is_enabled(
            "memory_learning_enabled", tenant_id, user_id
        )

        merged_metadata = dict(metadata or {})
        if session_id:
            merged_metadata.setdefault("session_id", session_id)
        if conversation_id:
            merged_metadata.setdefault("conversation_id", conversation_id)

        if shadow_mode or not learning_enabled:
            result = await super().process_interaction(
                text=text,
                tenant_id=tenant_id,
                user_id=user_id,
                source_type=source_type,
                source_ref=source_ref,
                metadata=merged_metadata,
            )
            result["write_authority"] = "disabled_or_shadow"
            return result

        _base._METRICS["interactions_processed"] += 1
        result = await self._formation_service.process_interaction(
            text=text,
            tenant_id=tenant_id,
            user_id=user_id,
            source_type=source_type,
            source_ref=source_ref,
            metadata=merged_metadata,
            request_id=request_id or kwargs.get("request_id"),
            correlation_id=correlation_id or kwargs.get("correlation_id"),
            actor_id=actor_id or kwargs.get("actor_id"),
            session_id=session_id or kwargs.get("session_id"),
            conversation_id=conversation_id or kwargs.get("conversation_id"),
            policy_context=policy_context or kwargs.get("policy_context"),
        )
        _base._METRICS["signals_extracted"] += int(result.get("extracted") or 0)
        _base._METRICS["signals_admitted"] += int(result.get("admitted") or 0)
        _base._METRICS["ledger_writes"] += int(result.get("persisted") or 0)
        _base._METRICS["projection_failures"] += int(
            result.get("projection_failures") or 0
        )
        result["write_authority"] = "neurovault"
        return result

    async def recall_context(
        self,
        user_id: Any,
        query: str,
        top_k: int = 10,
        tiers: Sequence[str] | None = None,
        tenant_id: str | None = None,
        include_embeddings: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _base._METRICS["recall_requests"] += 1

        resolved_user_id = user_id
        if isinstance(user_id, dict):
            resolved_user_id = user_id.get("user_id") or user_id.get("id")

        resolved_tenant = str(tenant_id or "").strip()
        if not resolved_tenant or resolved_tenant == "default":
            raise RecallScopeError("explicit non-default tenant_id is required for memory recall")
        if not str(resolved_user_id or "").strip():
            raise RecallScopeError("user_id is required for memory recall")

        request = RecallRequest(
            query=str(query or ""),
            tenant_id=resolved_tenant,
            user_id=str(resolved_user_id),
            top_k=int(top_k or 10),
            conversation_id=kwargs.get("conversation_id"),
            session_id=kwargs.get("session_id"),
            correlation_id=kwargs.get("correlation_id"),
            request_id=kwargs.get("request_id"),
            namespaces=tuple(str(tier) for tier in (tiers or ())),
            metadata={
                "include_embeddings": bool(include_embeddings),
                "latency_budget_ms": kwargs.get("latency_budget_ms"),
            },
        )
        result = await self._neuro_recall.recall(request)

        formatted: list[dict[str, Any]] = []
        for item in result.memories:
            payload = item.to_dict()
            formatted.append(
                {
                    "id": item.id,
                    "content": item.content,
                    "metadata": payload.get("metadata", {}),
                    "timestamp": item.timestamp.timestamp(),
                    "similarity_score": item.relevance,
                    "memory_type": item.memory_type.value,
                    "result": item.content,
                }
            )

        _base._METRICS["recall_hits"] += len(formatted)
        return {
            "results": formatted,
            "status": "degraded" if result.degraded else "success",
            "count": len(formatted),
            "source": "neuro_recall",
            "degraded": result.degraded,
            "degradation_reason": result.degradation_reason,
            "provenance": list(result.provenance),
            "latency_ms": result.latency_ms,
        }

    async def inspect_memory_state(self, **kwargs: Any) -> dict[str, Any]:
        return await self._control_service.inspect_memory_state(**kwargs)

    async def list_consent_scopes(self, **kwargs: Any) -> dict[str, Any]:
        return await self._control_service.list_consent_scopes(**kwargs)

    async def set_consent_scope(self, **kwargs: Any) -> dict[str, Any]:
        return await self._control_service.set_consent_scope(**kwargs)

    async def list_retention_policies(self, **kwargs: Any) -> dict[str, Any]:
        return await self._control_service.list_retention_policies(**kwargs)

    async def set_retention_policy(self, **kwargs: Any) -> dict[str, Any]:
        return await self._control_service.set_retention_policy(**kwargs)


memory_manager = MemoryRuntimeManager()
_base.bind_memory_manager(memory_manager)


def get_memory_manager() -> MemoryRuntimeManager:
    return memory_manager


def get_memory_control_service() -> MemoryControlService:
    return memory_manager.control_service


def init_memory() -> MemoryRuntimeManager:
    logger.info("Initializing canonical memory runtime manager")
    return memory_manager


async def close() -> None:
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
    **kwargs: Any,
) -> dict[str, Any]:
    del activation
    return await memory_manager.recall_context(
        user_id=user_id,
        tenant_id=tenant_id,
        query=query,
        conversation_id=conversation_id,
        session_id=session_id,
        top_k=top_k,
        correlation_id=correlation_id,
        tiers=tiers,
        include_embeddings=include_embeddings,
        **kwargs,
    )


update_memory = _base.update_memory
export_promoted_artifacts = _base.export_promoted_artifacts
get_metrics = _base.get_metrics


__all__ = [
    "MemoryRuntimeManager",
    "close",
    "export_promoted_artifacts",
    "get_memory_control_service",
    "get_memory_manager",
    "get_metrics",
    "init_memory",
    "memory_manager",
    "recall_context",
    "update_memory",
]
