"""Adversarial graph-evidence selection and presentation contract.

These tests exercise a real NeuroRecall selection followed by the existing
selected-graph projector. They do not claim a cached RecallResult is a durable
authorization grant or substitute for live PostgreSQL integration proof.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    NeuroRecall,
    RecallRequest,
    RecallScopeError,
)
from ai_karen_engine.core.memory.retrieval.selected_graph_projection import (
    project_selected_memory_graph,
)
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata


class _Retriever:
    def __init__(self, memories: list[MemoryEntry]) -> None:
        self.memories = memories

    async def recall(self, query):
        return list(self.memories)


class _SourceAuthorizer:
    def __init__(self) -> None:
        self.allowed = True
        self.raise_on_check = False
        self.calls: list[tuple[str, str, str]] = []

    async def authorize(self, memory: MemoryEntry, request: RecallRequest) -> bool:
        self.calls.append((str(memory.id), request.tenant_id, request.user_id))
        if self.raise_on_check:
            raise RuntimeError("private-source-auth-token-never-export")
        return self.allowed


def _request(**overrides) -> RecallRequest:
    fields = {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "query": "Where was the connector mentioned?",
        "correlation_id": "graph-selection-proof",
    }
    fields.update(overrides)
    return RecallRequest(**fields)


def _candidate(
    *,
    event_id: str = "graph-event-1",
    tenant_id: str = "tenant-1",
    user_id: str = "user-1",
    source_type: str = "plugin",
    source_ref: str | None = "connector-1",
) -> MemoryEntry:
    provenance = {
        "store": "postgres",
        "record_type": "memory_event",
        "event_id": event_id,
        "source_type": source_type,
        "source_ref": source_ref,
        "graph_relationship": "MENTIONS",
        "graph_depth": 1,
        "matched_entity_cue": "Connector",
    }
    return MemoryEntry(
        id=event_id,
        content="Private connector memory, not permitted in display output",
        metadata=MemoryMetadata(
            tenant_id=tenant_id,
            user_id=user_id,
            source="postgres_graph",
            custom={
                "source_store": "postgres_graph",
                "provenance": provenance,
                "graph_depth": 1,
                "graph_relationship": "MENTIONS",
                "source_lineage": {
                    "source_id": "connector-1",
                    "authorization_status": "authorized",
                },
            },
        ),
    )


@pytest.mark.asyncio
async def test_live_authorization_rechecked_for_each_graph_selection() -> None:
    authorizer = _SourceAuthorizer()
    candidate = _candidate()
    recall = NeuroRecall(_Retriever([candidate]), source_authorizer=authorizer)
    request = _request()

    granted = await recall.recall(request)
    assert [item.id for item in granted.memories] == ["graph-event-1"]
    visible = project_selected_memory_graph(request=request, result=granted)
    assert visible["status"] == "available"
    assert len(visible["edges"]) == 1
    assert candidate.content not in str(visible)
    assert candidate.id not in str(visible)
    assert "connector-1" not in str(visible)

    authorizer.allowed = False
    revoked = await recall.recall(request)
    assert revoked.memories == ()
    assert revoked.provenance == ()
    denied = project_selected_memory_graph(request=request, result=revoked)
    assert denied["status"] == "empty"
    assert denied["nodes"] == []
    assert denied["edges"] == []
    assert authorizer.calls == [
        ("graph-event-1", "tenant-1", "user-1"),
        ("graph-event-1", "tenant-1", "user-1"),
    ]


@pytest.mark.asyncio
async def test_forged_lineage_flag_cannot_override_revocation() -> None:
    authorizer = _SourceAuthorizer()
    authorizer.allowed = False
    candidate = _candidate()
    candidate.metadata.custom["source_lineage"]["authorization_status"] = "authorized"
    request = _request()
    selected = await NeuroRecall(
        _Retriever([candidate]), source_authorizer=authorizer
    ).recall(request)
    graph = project_selected_memory_graph(request=request, result=selected)
    assert selected.memories == ()
    assert graph["status"] == "empty"
    assert "Connector" not in str(graph)
    assert authorizer.calls == [("graph-event-1", "tenant-1", "user-1")]


@pytest.mark.asyncio
async def test_source_verifier_failure_does_not_expose_private_error() -> None:
    authorizer = _SourceAuthorizer()
    authorizer.raise_on_check = True
    request = _request()
    result = await NeuroRecall(
        _Retriever([_candidate()]), source_authorizer=authorizer
    ).recall(request)
    graph = project_selected_memory_graph(request=request, result=result)
    assert result.memories == ()
    assert graph["edges"] == []
    assert "private-source-auth-token-never-export" not in repr(result)
    assert "private-source-auth-token-never-export" not in str(graph)


@pytest.mark.asyncio
async def test_cross_tenant_graph_candidate_never_becomes_selected_graph() -> None:
    authorizer = _SourceAuthorizer()
    request = _request()
    result = await NeuroRecall(
        _Retriever([_candidate(tenant_id="tenant-other")]),
        source_authorizer=authorizer,
    ).recall(request)
    graph = project_selected_memory_graph(request=request, result=result)
    assert result.memories == ()
    assert graph["edges"] == []
    assert authorizer.calls == []


@pytest.mark.asyncio
async def test_modified_selected_receipt_cannot_upgrade_graph_evidence() -> None:
    authorizer = _SourceAuthorizer()
    request = _request()
    selected = await NeuroRecall(
        _Retriever([_candidate()]), source_authorizer=authorizer
    ).recall(request)
    assert selected.memories
    # A forged receipt with a different event identity must not become a link,
    # even when the source was authorized during actual selection.
    from dataclasses import replace

    forged = deepcopy(selected.provenance[0])
    forged["provenance"]["event_id"] = "another-tenant-event"
    tampered = replace(selected, provenance=(forged,))
    graph = project_selected_memory_graph(request=request, result=tampered)
    assert graph["status"] == "empty"
    assert graph["edges"] == []


@pytest.mark.asyncio
async def test_selection_cannot_be_replayed_under_different_request_scope() -> None:
    request = _request()
    selected = await NeuroRecall(
        _Retriever([_candidate()]), source_authorizer=_SourceAuthorizer()
    ).recall(request)
    with pytest.raises(RecallScopeError):
        project_selected_memory_graph(
            request=_request(tenant_id="tenant-other"), result=selected
        )
    with pytest.raises(RecallScopeError):
        project_selected_memory_graph(
            request=_request(query="Different user question"), result=selected
        )
