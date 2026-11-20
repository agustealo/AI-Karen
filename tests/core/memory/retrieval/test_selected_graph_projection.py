"""Selected graph projection uses NeuroRecall output, never raw graph traversal."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_karen_engine.core.memory.retrieval.neuro_recall import (
    RecallRequest,
    RecallResult,
    RecallScopeError,
    NeuroRecall,
)
from ai_karen_engine.core.memory.retrieval.selected_graph_projection import (
    MAX_GRAPH_EVENTS,
    project_selected_memory_graph,
)
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata


def _request(**changes) -> RecallRequest:
    values = {
        "query": "Where is Supabase mentioned?",
        "tenant_id": "tenant-one",
        "user_id": "user-one",
    }
    values.update(changes)
    return RecallRequest(**values)


def _selected(
    event_id: str = "event-one",
    *,
    tenant_id: str = "tenant-one",
    user_id: str = "user-one",
    source: str = "postgres_graph",
    relationship: str = "MENTIONS",
    depth: int = 1,
    cue: str = "Supabase",
):
    provenance = {
        "store": "postgres",
        "record_type": "memory_event",
        "event_id": event_id,
        "source_type": "conversation",
        "source_ref": "message-1",
        "matched_entity_cue": cue,
        "graph_relationship": relationship,
        "graph_depth": depth,
    }
    memory = MemoryEntry(
        id=event_id,
        content="Internal details should never enter the graph payload",
        metadata=MemoryMetadata(
            tenant_id=tenant_id,
            user_id=user_id,
            source=source,
            custom={
                "source_store": source,
                "provenance": provenance,
                "graph_depth": depth,
            },
        ),
    )
    receipt = {
        "memory_id": event_id,
        "source": source,
        "provenance": deepcopy(provenance),
    }
    return memory, receipt


def _result(request: RecallRequest, entries=(), receipts=(), **overrides) -> RecallResult:
    return RecallResult(
        memories=tuple(entries),
        tenant_id=overrides.get("tenant_id", request.tenant_id),
        user_id=overrides.get("user_id", request.user_id),
        query=overrides.get("query", request.query),
        latency_ms=5.0,
        provenance=tuple(receipts),
        degraded=overrides.get("degraded", False),
        degradation_reason=overrides.get("degradation_reason"),
    )


def test_exact_selected_graph_event_emits_only_bounded_opaque_mentions():
    request = _request()
    memory, receipt = _selected()
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["status"] == "available"
    assert [node["kind"] for node in graph["nodes"]] == ["memory_event", "entity_cue"]
    assert graph["nodes"][1]["verification_state"] == "retrieval_cue"
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["type"] == "MENTIONS"
    text = str(graph)
    assert memory.content not in text
    assert memory.id not in text
    assert request.tenant_id not in text
    assert request.user_id not in text
    assert "graph_path" not in text
    assert graph == project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )


@pytest.mark.parametrize("changes", [
    {"tenant_id": ""},
    {"tenant_id": "default"},
    {"user_id": ""},
    {"query": ""},
])
def test_invalid_scope_rejected(changes):
    request = _request(**changes)
    with pytest.raises(RecallScopeError):
        project_selected_memory_graph(request=request, result=_result(request))


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other-tenant"},
    {"user_id": "other-user"},
    {"query": "Other question"},
])
def test_result_scope_and_query_mismatch_rejected(changes):
    request = _request()
    with pytest.raises(RecallScopeError):
        project_selected_memory_graph(request=request, result=_result(request, **changes))


def test_foreign_memory_never_published_even_in_matching_result():
    request = _request()
    memory, receipt = _selected(tenant_id="other-tenant")
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["status"] == "empty"
    assert graph["nodes"] == []


def test_raw_candidate_without_selection_receipt_never_published():
    request = _request()
    memory, _ = _selected()
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [])
    )
    assert graph["edges"] == []


def test_tampered_receipt_does_not_authorize_graph():
    request = _request()
    memory, receipt = _selected()
    receipt["provenance"]["matched_entity_cue"] = "Private Person"
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["nodes"] == []


@pytest.mark.parametrize("change", [
    {"source": "stm"},
    {"relationship": "CAUSED"},
    {"depth": 2},
    {"cue": " "},
    {"cue": "x" * 121},
])
def test_unproven_or_non_direct_relations_are_not_inferred(change):
    request = _request()
    memory, receipt = _selected(**change)
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["edges"] == []


def test_duplicate_entities_are_deduplicated_and_events_bounded():
    request = _request()
    items = [_selected(f"event-{i}") for i in range(MAX_GRAPH_EVENTS + 2)]
    graph = project_selected_memory_graph(
        request=request,
        result=_result(
            request,
            [item[0] for item in items],
            [item[1] for item in items],
            degraded=True,
            degradation_reason="partial_retrieval_failure",
        ),
    )
    assert len(graph["edges"]) == MAX_GRAPH_EVENTS
    assert len([n for n in graph["nodes"] if n["kind"] == "entity_cue"]) == 1
    assert graph["truncated"] is True
    assert graph["degraded"] is True
    assert graph["degradation_reason"] == "partial_retrieval_failure"


def test_no_cognitive_graph_output_for_source_only_retrieval():
    request = _request()
    memory, receipt = _selected(source="web")
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["status"] == "empty"


def test_duplicate_selection_receipts_fail_closed():
    request = _request()
    memory, receipt = _selected()
    duplicate = deepcopy(receipt)
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt, duplicate])
    )
    assert graph["status"] == "empty"
    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_graph_depth_mismatch_between_source_and_metadata_is_rejected():
    request = _request()
    memory, receipt = _selected()
    memory.metadata.custom["provenance"]["graph_depth"] = 2
    receipt["provenance"]["graph_depth"] = 2
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["edges"] == []


def test_unselected_receipt_is_not_published_as_graph():
    request = _request()
    memory, receipt = _selected()
    extra = deepcopy(receipt)
    extra["memory_id"] = "unselected-event"
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [extra])
    )
    assert graph["status"] == "empty"


def test_unresolved_cue_does_not_claim_canonical_entity_identity():
    request = _request()
    memory, receipt = _selected(cue="Ambiguous Person")
    memory.metadata.custom["provenance"]["entity_resolution"] = None
    receipt["provenance"]["entity_resolution"] = None
    graph = project_selected_memory_graph(
        request=request, result=_result(request, [memory], [receipt])
    )
    assert graph["nodes"][1]["kind"] == "entity_cue"
    assert graph["nodes"][1]["verification_state"] == "retrieval_cue"
    assert "entity_id" not in graph["nodes"][1]


class _ControlledRetriever:
    def __init__(self, memories):
        self.memories = memories

    async def recall(self, query):
        return list(self.memories)


@pytest.mark.asyncio
async def test_projector_only_sees_neuro_recall_selected_memories():
    request = _request(top_k=1)
    allowed, _ = _selected(event_id="allowed-event")
    excluded, _ = _selected(event_id="excluded-event", tenant_id="other-tenant")
    result = await NeuroRecall(
        _ControlledRetriever([allowed, excluded]),
    ).recall(request)
    assert [entry.id for entry in result.memories] == ["allowed-event"]
    graph = project_selected_memory_graph(request=request, result=result)
    assert graph["status"] == "available"
    assert len(graph["edges"]) == 1
    assert "allowed-event" not in str(graph)
    assert "excluded-event" not in str(graph)


@pytest.mark.asyncio
async def test_neuro_recall_rejection_never_becomes_a_display_edge():
    request = _request()
    rejected, _ = _selected(event_id="rejected-event", user_id="another-user")
    selected = await NeuroRecall(
        _ControlledRetriever([rejected])
    ).recall(request)
    assert selected.memories == ()
    graph = project_selected_memory_graph(request=request, result=selected)
    assert graph["status"] == "empty"
    assert graph["edges"] == []
