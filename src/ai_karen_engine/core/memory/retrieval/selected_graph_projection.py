"""Fail-closed display projection of graph evidence selected by NeuroRecall.

This is neither a graph query endpoint nor a new recall strategy. Only a
trusted RecallResult from the runtime's completed NeuroRecall selection may
enter this projector. No intermediate traversal path, raw database identifier,
memory content or source reference is published.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .neuro_recall import RecallResult, RecallRequest, RecallScopeError

MAX_GRAPH_EVENTS = 12
MAX_LABEL_LENGTH = 120


def _opaque_id(kind: str, tenant: str, user: str, value: str) -> str:
    key = f"{tenant}\0{user}\0{kind}\0{value}"
    return f"{kind}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"


def project_selected_memory_graph(
    *, request: RecallRequest, result: RecallResult
) -> dict[str, Any]:
    """Project bounded MENTIONS links backed by selected graph memory events.

    The result is deliberately conservative. A valid selected memory without
    graph-event evidence produces no graph edge. More relationships require
    their own reviewed provenance and live ACL contracts.
    """
    request.validate()
    if result.tenant_id != request.tenant_id or result.user_id != request.user_id:
        raise RecallScopeError("recall result does not match the request scope")
    if result.query != request.query:
        raise RecallScopeError("recall result does not match the request query")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    seen_events: set[str] = set()
    selected_provenance: dict[str, dict[str, Any]] = {}
    ambiguous_receipt_ids: set[str] = set()
    visible_memories = result.memories[:MAX_GRAPH_EVENTS]
    selected_ids = {str(memory.id) for memory in visible_memories}

    for receipt in result.provenance:
        if not isinstance(receipt, Mapping):
            continue
        memory_id = receipt.get("memory_id")
        if not isinstance(memory_id, str) or memory_id not in selected_ids:
            continue
        # A conflicting or duplicate receipt must never upgrade a candidate
        # into displayable evidence. Discard ambiguous entries fail-closed.
        if memory_id in selected_provenance:
            ambiguous_receipt_ids.add(memory_id)
            continue
        selected_provenance[memory_id] = dict(receipt)

    for memory in visible_memories:
        metadata = memory.metadata
        if metadata is None:
            continue
        if metadata.tenant_id != request.tenant_id or metadata.user_id != request.user_id:
            continue
        memory_id = str(memory.id or "")
        receipt = selected_provenance.get(memory_id)
        if memory_id in ambiguous_receipt_ids:
            continue
        custom = metadata.custom
        if not memory_id or not receipt or not isinstance(custom, dict):
            continue
        provenance = custom.get("provenance")
        recorded = receipt.get("provenance")
        if not isinstance(provenance, dict) or not isinstance(recorded, dict):
            continue
        if provenance != recorded:
            continue
        if (
            metadata.source != "postgres_graph"
            or custom.get("source_store") != "postgres_graph"
            or receipt.get("source") != "postgres_graph"
            or provenance.get("store") != "postgres"
            or provenance.get("record_type") != "memory_event"
            or provenance.get("graph_relationship") != "MENTIONS"
            or provenance.get("event_id") != memory_id
            or custom.get("graph_depth") != 1
            or provenance.get("graph_depth") != 1
            or custom.get("graph_relationship") not in (None, "MENTIONS")
        ):
            continue
        cue = provenance.get("matched_entity_cue")
        if not isinstance(cue, str) or not cue.strip() or len(cue) > MAX_LABEL_LENGTH:
            continue
        cue = cue.strip()
        event_node = _opaque_id("memory_event", request.tenant_id, request.user_id, memory_id)
        entity_node = _opaque_id("entity", request.tenant_id, request.user_id, cue.casefold())
        if event_node in seen_events:
            continue
        seen_events.add(event_node)
        nodes.append({
            "id": event_node,
            "kind": "memory_event",
            "label": "Selected memory event",
            "verification_state": "neuro_recall_selected",
        })
        if entity_node not in seen_entities:
            seen_entities.add(entity_node)
            nodes.append({
                "id": entity_node,
                "kind": "entity",
                "label": cue,
                "verification_state": "source_matched",
            })
        edges.append({
            "id": _opaque_id("edge", request.tenant_id, request.user_id, f"{event_node}\0{entity_node}"),
            "from": event_node,
            "to": entity_node,
            "type": "MENTIONS",
            "verification_state": "selected_memory_provenance",
        })

    return {
        "version": 1,
        "kind": "selected_memory_graph",
        "status": "available" if edges else "empty",
        "nodes": nodes,
        "edges": edges,
        "truncated": len(result.memories) > MAX_GRAPH_EVENTS,
        "degraded": result.degraded,
        "degradation_reason": result.degradation_reason,
    }


__all__ = ["project_selected_memory_graph"]
