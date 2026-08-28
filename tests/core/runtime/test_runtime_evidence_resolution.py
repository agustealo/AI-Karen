from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirement,
    ContextRequirements,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.cortex.context_stages import finalize_decision_with_context
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


class RecordingMemoryManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def recall_context(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return {
            "results": [
                {
                    "id": "memory-1",
                    "content": "User prefers local-first execution.",
                    "timestamp": 1_700_000_000.0,
                    "similarity_score": 0.91,
                    "memory_type": "semantic",
                    "metadata": {"confidence": 0.87},
                }
            ],
            "status": "success",
            "source": "neuro_recall",
            "degraded": False,
            "degradation_reason": None,
            "provenance": ["postgres"],
            "latency_ms": 8.5,
        }


class RejectingMemoryManager:
    async def recall_context(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        raise RuntimeError("explicit non-default tenant_id is required for memory recall")


def _request(*, tenant_id: str = "tenant-1") -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Use what you remember about my runtime."}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id=tenant_id,
            session_id="session-1",
            conversation_id="conversation-1",
            request_id="request-1",
            correlation_id="correlation-1",
        ),
    )


def _authorized_context(request: ChatExecutionRequest) -> CognitiveContext:
    ctx = request.context
    requirements = ContextRequirements(
        request_id=ctx.request_id or "",
        correlation_id=ctx.correlation_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        conversation_id=ctx.conversation_id,
        requirements=[
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
                scopes=["session"],
                classes=["semantic"],
                max_items=5,
            )
        ],
    )
    return CognitiveContext(
        context_id="context-1",
        request_id=ctx.request_id or "",
        correlation_id=ctx.correlation_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        requirements=requirements,
        authorized_sources=[EvidenceSource.MEMORY.value],
        unresolved_sources=[EvidenceSource.MEMORY.value],
        policy_decision_id="policy-context-1",
    )


@pytest.mark.asyncio
async def test_runtime_evidence_resolver_calls_memory_authority_once_and_types_result() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    memory_manager = RecordingMemoryManager()
    resolver = RuntimeEvidenceResolver(memory_manager=memory_manager)

    resolved = await resolver.resolve(request, cognitive_context)

    assert resolved is cognitive_context
    assert len(memory_manager.calls) == 1
    call = memory_manager.calls[0]
    assert call["tenant_id"] == "tenant-1"
    assert call["user_id"] == "user-1"
    assert call["conversation_id"] == "conversation-1"
    assert call["session_id"] == "session-1"
    assert call["request_id"] == "request-1"
    assert call["top_k"] == 5
    assert call["tiers"] == ("semantic",)

    assert resolved.unresolved_sources == []
    assert len(resolved.evidence) == 1
    evidence = resolved.evidence[0]
    assert evidence.source is EvidenceSource.MEMORY
    assert evidence.evidence_id == "memory-1"
    assert evidence.relevance == pytest.approx(0.91)
    assert evidence.confidence == pytest.approx(0.87)
    assert evidence.provenance.resolver_id == "runtime.evidence.memory"
    assert evidence.provenance.retrieval_method == "neuro_recall"
    assert evidence.scope is not None
    assert evidence.scope.tenant_id == "tenant-1"
    assert evidence.scope.user_id == "user-1"
    assert resolved.metadata["memory_recall_count"] == 1
    assert resolved.metadata["memory_response_source"] == "neuro_recall"


@pytest.mark.asyncio
async def test_failed_memory_scope_remains_unresolved_and_degraded() -> None:
    request = _request(tenant_id="default")
    cognitive_context = _authorized_context(request)
    resolver = RuntimeEvidenceResolver(memory_manager=RejectingMemoryManager())

    resolved = await resolver.resolve(request, cognitive_context)

    assert resolved.evidence == []
    assert resolved.unresolved_sources == [EvidenceSource.MEMORY.value]
    assert resolved.metadata["memory_recall_status"] == "failed"
    assert resolved.metadata["memory_degraded"] is True
    assert "non-default tenant_id" in resolved.metadata["memory_degradation_reason"]


def test_cortex_stage_2_carries_same_resolved_context() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    now = datetime.now(timezone.utc)
    cognitive_context.evidence.append(
        ContextEvidence(
            evidence_id="memory-1",
            source=EvidenceSource.MEMORY,
            content="User prefers local-first execution.",
            source_ref="memory-1",
            relevance=0.91,
            confidence=0.87,
            provenance=EvidenceProvenance(
                source_ref="memory-1",
                source_record_id="memory-1",
                resolver_id="runtime.evidence.memory",
                resolver_version="1",
                retrieval_method="neuro_recall",
                retrieved_at=now,
            ),
            temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
            scope=EvidenceScope(
                tenant_id="tenant-1",
                user_id="user-1",
                session_id="session-1",
                conversation_id="conversation-1",
            ),
        )
    )
    cognitive_context.unresolved_sources.clear()
    preliminary = ExecutionDecision(
        memory_recall_required=True,
        memory_top_k=5,
        required_capabilities=["memory.read"],
    )

    finalized = finalize_decision_with_context(preliminary, cognitive_context)

    assert finalized.cognitive_context is cognitive_context
    assert "context_memory_resolved" in finalized.reason_codes
    assert "context_memory_evidence_available" in finalized.reason_codes
    assert finalized.policy_constraints["context_memory_evidence_count"] == 1


@pytest.mark.asyncio
async def test_chat_runtime_consumes_typed_evidence_without_retrieving_again() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    now = datetime.now(timezone.utc)
    cognitive_context.evidence.append(
        ContextEvidence(
            evidence_id="memory-1",
            source=EvidenceSource.MEMORY,
            content="User prefers local-first execution.",
            source_ref="memory-1",
            relevance=0.91,
            confidence=0.87,
            provenance=EvidenceProvenance(
                resolver_id="runtime.evidence.memory",
                retrieval_method="neuro_recall",
                retrieved_at=now,
            ),
            temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
            scope=EvidenceScope(tenant_id="tenant-1", user_id="user-1"),
        )
    )
    cognitive_context.unresolved_sources.clear()
    cognitive_context.metadata.update(
        {
            "memory_recall_status": "success",
            "memory_recall_count": 1,
            "memory_latency_ms": 8.5,
            "memory_degraded": False,
        }
    )
    decision = ExecutionDecision(
        memory_recall_required=True,
        memory_top_k=5,
        cognitive_context=cognitive_context,
    )

    runtime = object.__new__(ChatRuntime)
    meta = await runtime._consume_resolved_memory(request, decision)

    assert not hasattr(ChatRuntime, "_recall_memory")
    assert meta["memory_recall_count"] == 1
    recall = meta["memory_context"]["recall"]
    assert recall == request.metadata["memory_context"]["recall"]
    assert recall[0]["id"] == "memory-1"
    assert recall[0]["content"] == "User prefers local-first execution."
    assert recall[0]["relevance"] == pytest.approx(0.91)
    assert recall[0]["confidence"] == pytest.approx(0.87)
