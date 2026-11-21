"""KIS-GRAPH-01C2P: fresh runtime memory resolution after source revocation.

A freshly built CognitiveContext must reflect the result of the current
NeuroRecall source ACL check, not a prior turn's authorized memory. This is an
in-process runtime composition test, not proof of deployed publication timing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceSource,
)
from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall,
    RecallRequest,
)
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver


class _Retriever:
    async def recall(self, query):
        return [
            MemoryEntry(
                id="connector-event",
                content="Private graph memory from an external connector",
                timestamp=datetime.now(timezone.utc),
                metadata=MemoryMetadata(
                    tenant_id="tenant-1",
                    user_id="user-1",
                    source="postgres_graph",
                    custom={
                        "source_store": "postgres_graph",
                        "provenance": {
                            "store": "postgres",
                            "record_type": "memory_event",
                            "event_id": "connector-event",
                            "source_type": "plugin",
                            "source_ref": "connector-source-1",
                            "graph_relationship": "MENTIONS",
                            "graph_depth": 1,
                            "matched_entity_cue": "Connector",
                        },
                        "graph_depth": 1,
                    },
                ),
            )
        ]


class _CurrentACL:
    def __init__(self):
        self.allowed = True
        self.calls = 0

    async def authorize(self, memory, request):
        self.calls += 1
        assert request.tenant_id == "tenant-1"
        assert request.user_id == "user-1"
        return self.allowed


class _CanonicalMemoryManager:
    """Thin test transport around the real NeuroRecall selection contract."""

    def __init__(self, recall):
        self.recall = recall
        self.calls = 0

    async def recall_context(self, *, user_id, tenant_id, query, top_k, **kwargs):
        self.calls += 1
        selected = await self.recall.recall(
            RecallRequest(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                query=str(query),
                top_k=max(1, int(top_k)),
                correlation_id=kwargs.get("correlation_id"),
            )
        )
        return {
            "results": [
                {
                    "id": item.id,
                    "content": item.content,
                    "timestamp": item.timestamp,
                    "metadata": item.to_dict().get("metadata", {}),
                    "memory_type": item.memory_type.value,
                    "similarity_score": item.relevance,
                }
                for item in selected.memories
            ],
            "status": "success",
            "source": "neuro_recall",
            "provenance": list(selected.provenance),
        }


class _PersonaPreferences:
    enable_persona_memory_filtering = False
    cross_persona_memory_sharing = True
    active_persona_id = None


class _PersonaService:
    async def get_user_preferences(self, **kwargs):
        return _PersonaPreferences()


def _request():
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "What did my connector mention?"}],
        context=ChatExecutionContext(
            tenant_id="tenant-1", user_id="user-1", session_id="session-1"
        ),
    )


def _context():
    requirement = ContextRequirement(
        source=EvidenceSource.MEMORY,
        capability="memory_recall",
        max_items=5,
    )
    requirements = ContextRequirements(
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
        user_id="user-1",
        requirements=[requirement],
    )
    return CognitiveContext(
        context_id="context-1",
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
        user_id="user-1",
        requirements=requirements,
        authorized_sources=[EvidenceSource.MEMORY.value],
        unresolved_sources=[EvidenceSource.MEMORY.value],
    )


@pytest.mark.asyncio
async def test_new_runtime_context_rechecks_current_graph_source_acl():
    acl = _CurrentACL()
    manager = _CanonicalMemoryManager(
        NeuroRecall(_Retriever(), source_authorizer=acl)
    )
    resolver = RuntimeEvidenceResolver(
        memory_manager=manager,
        persona_service=_PersonaService(),
    )
    request = _request()

    first = await resolver.resolve(request, _context())
    assert len(first.evidence) == 1
    assert "Private graph memory" in first.evidence[0].content
    assert first.metadata["memory_recall_count"] == 1
    assert first.metadata["memory_response_source"] == "neuro_recall"

    acl.allowed = False
    second = await resolver.resolve(request, _context())
    assert second.evidence == []
    assert second.metadata["memory_recall_count"] == 0
    assert second.metadata["memory_provenance"] == ()
    assert manager.calls == 2
    assert acl.calls == 2
    assert "Private graph memory" not in repr(second)


@pytest.mark.asyncio
async def test_current_source_acl_denial_never_resolves_memory_evidence():
    acl = _CurrentACL()
    acl.allowed = False
    manager = _CanonicalMemoryManager(
        NeuroRecall(_Retriever(), source_authorizer=acl)
    )
    resolver = RuntimeEvidenceResolver(
        memory_manager=manager,
        persona_service=_PersonaService(),
    )
    result = await resolver.resolve(_request(), _context())
    assert result.evidence == []
    assert result.metadata["memory_recall_count"] == 0
    assert acl.calls == 1
