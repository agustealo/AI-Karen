"""KCOG-RESEARCH-01: dependency-free, research-only associative ranking.

Compare KAREN's *actual* SpreadingActivation primitive against an independently
implemented weighted Personalized PageRank reference on synthetic graphs.

These are deterministic algorithm/permission-fixture tests, NOT proof of
live PostgreSQL authorization, source ACLs, embeddings, latency or user value.
Do not import this reference implementation into KAREN's production runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

import pytest

from ai_karen_engine.core.memory.associative.spreading_activation import (
    AssociationGraph,
    SpreadingActivation,
)


@dataclass(frozen=True)
class _RankRun:
    scores: dict[str, float]
    iterations: int
    converged: bool


def _weighted_ppr_reference(
    adjacency: Mapping[str, Mapping[str, float]],
    seeds: Mapping[str, float],
    *,
    damping: float = 0.5,
    tolerance: float = 1e-12,
    max_iterations: int = 200,
    max_nodes: int = 128,
) -> _RankRun:
    """Run a bounded weighted walk with restart on an undirected graph.

    The seed distribution is normalized. Dangling mass returns to the seed
    distribution. A non-converged run is explicitly reported, never hidden.
    This is mathematically inspired by PPR, not a copy of HippoRAG/igraph.
    """
    if not isinstance(damping, (int, float)) or not isfinite(damping) or not 0 <= damping < 1:
        raise ValueError("damping must be finite and in [0, 1)")
    if not isinstance(tolerance, (int, float)) or not isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be positive and finite")
    if not isinstance(max_iterations, int) or not 1 <= max_iterations <= 500:
        raise ValueError("max_iterations must be 1..500")
    if not isinstance(max_nodes, int) or not 1 <= max_nodes <= 1024:
        raise ValueError("max_nodes must be 1..1024")
    nodes = tuple(sorted(adjacency))
    if not nodes or len(nodes) > max_nodes:
        raise ValueError("graph size outside allowed research budget")
    node_set = set(nodes)

    for source, neighbors in adjacency.items():
        if not isinstance(source, str) or not source.strip():
            raise ValueError("node identifiers must be nonempty strings")
        for target, value in neighbors.items():
            if source == target or target not in node_set:
                raise ValueError("graph must contain only in-scope non-self edges")
            if (
                not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError("graph edge weights must be positive and finite")
            reverse = adjacency[target].get(source)
            if reverse is None or not isfinite(reverse) or abs(value - reverse) > 1e-9:
                raise ValueError("research graph must be explicitly undirected")

    if not seeds or any(node not in node_set for node in seeds):
        raise ValueError("seeds must reference graph nodes")
    for weight in seeds.values():
        if not isinstance(weight, (int, float)) or not isfinite(weight) or weight < 0:
            raise ValueError("seed weights must be non-negative and finite")
    total = sum(seeds.values())
    if not isfinite(total) or total <= 0:
        raise ValueError("seed distribution must have positive finite mass")

    restart = {node: seeds.get(node, 0.0) / total for node in nodes}
    previous = dict(restart)
    for iteration in range(1, max_iterations + 1):
        next_rank = {node: (1 - damping) * restart[node] for node in nodes}
        dangling_mass = 0.0

        for source in nodes:
            neighbors = adjacency[source]
            if not neighbors:
                dangling_mass += previous[source]
                continue
            strength = sum(neighbors.values())
            for target, weight in neighbors.items():
                next_rank[target] += damping * previous[source] * (weight / strength)

        if dangling_mass:
            for node in nodes:
                next_rank[node] += damping * dangling_mass * restart[node]

        if max(abs(next_rank[node] - previous[node]) for node in nodes) <= tolerance:
            return _RankRun(next_rank, iteration, True)
        previous = next_rank

    return _RankRun(previous, max_iterations, False)


@dataclass(frozen=True)
class _ScopedNode:
    node_id: str
    tenant_id: str
    user_id: str
    consent_granted: bool = True


@dataclass(frozen=True)
class _ScopedEdge:
    source: str
    target: str
    tenant_id: str
    user_id: str
    weight: float = 1.0
    active: bool = True
    source_verified: bool = True


def _synthetic_authorized_view(
    nodes: tuple[_ScopedNode, ...],
    edges: tuple[_ScopedEdge, ...],
    *,
    tenant_id: str,
    user_id: str,
) -> dict[str, dict[str, float]]:
    """Construct only an illustrative scoped fixture view.

    No production authorizer is invoked here. Real PostgreSQL RLS/consent
    semantics must be tested separately against the canonical repository.
    """
    ids = [node.node_id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("ambiguous graph node identity")
    if not tenant_id or not user_id or tenant_id == "default":
        raise ValueError("explicit non-default principal required")
    allowed = {
        node.node_id
        for node in nodes
        if (
            node.tenant_id == tenant_id
            and node.user_id == user_id
            and node.consent_granted
        )
    }
    result: dict[str, dict[str, float]] = {node: {} for node in sorted(allowed)}
    for edge in edges:
        if (
            edge.tenant_id != tenant_id
            or edge.user_id != user_id
            or edge.source not in allowed
            or edge.target not in allowed
            or not edge.active
            or not edge.source_verified
            or edge.source == edge.target
        ):
            continue
        if not isfinite(edge.weight) or edge.weight <= 0:
            raise ValueError("invalid source-supported edge weight")
        # Duplicate evidence edges must not inflate PPR probability.
        w = max(edge.weight, result[edge.source].get(edge.target, 0.0))
        result[edge.source][edge.target] = w
        result[edge.target][edge.source] = w
    return result


def test_ppr_two_node_closed_form_and_mass() -> None:
    result = _weighted_ppr_reference(
        {"a": {"b": 1.0}, "b": {"a": 1.0}},
        {"a": 1.0},
    )
    assert result.converged
    assert result.iterations <= 200
    assert result.scores["a"] == pytest.approx(2 / 3)
    assert result.scores["b"] == pytest.approx(1 / 3)
    assert sum(result.scores.values()) == pytest.approx(1.0)


def test_weight_aware_ppr_distinguishes_relevant_path_from_equal_hops() -> None:
    # KAREN's real spreading activation uses hop decay rather than edge weight.
    baseline = SpreadingActivation(
        AssociationGraph(
            edges={
                "seed": ["hub"],
                "hub": ["seed", "relevant", "distractor"],
                "relevant": ["hub"],
                "distractor": ["hub"],
            },
            concept_index={"question": ["seed"]},
        ),
        activation_decay=0.5,
        max_propagation_depth=2,
    ).activate(["question"])

    # Synthetic evidence weights indicate relevant is the stronger relation.
    ppr = _weighted_ppr_reference(
        {
            "seed": {"hub": 1.0},
            "hub": {"seed": 1.0, "relevant": 5.0, "distractor": 1.0},
            "relevant": {"hub": 5.0},
            "distractor": {"hub": 1.0},
        },
        {"seed": 1.0},
    )
    assert baseline["relevant"] == pytest.approx(baseline["distractor"])
    assert ppr.converged
    assert ppr.scores["relevant"] > ppr.scores["distractor"]
    assert sum(ppr.scores.values()) == pytest.approx(1.0)
    # This is a constructed differential, not an improvement on real recall.


def test_multi_seed_and_dangling_graph_are_stable_and_deterministic() -> None:
    graph = {"seed": {}, "other": {}}
    one = _weighted_ppr_reference(graph, {"seed": 3.0, "other": 1.0})
    two = _weighted_ppr_reference(graph, {"other": 1.0, "seed": 3.0})
    assert one.converged and two.converged
    assert one.scores == two.scores
    assert one.scores["seed"] == pytest.approx(0.75)
    assert one.scores["other"] == pytest.approx(0.25)


def test_nonconvergence_is_reported_with_bounded_work() -> None:
    result = _weighted_ppr_reference(
        {"a": {"b": 1.0}, "b": {"a": 1.0}},
        {"a": 1.0},
        max_iterations=1,
    )
    assert not result.converged
    assert result.iterations == 1


@pytest.mark.parametrize(
    ("graph", "seeds"),
    [
        ({"a": {"b": 1.0}}, {"a": 1.0}),  # edge leaves bounded graph
        ({"a": {"b": 2.0}, "b": {"a": 1.0}}, {"a": 1.0}),
        ({"a": {"a": 1.0}}, {"a": 1.0}),
        ({"a": {"b": float("nan")}, "b": {"a": float("nan")}}, {"a": 1.0}),
        ({"a": {"b": float("inf")}, "b": {"a": float("inf")}}, {"a": 1.0}),
        ({"a": {"b": 0.0}, "b": {"a": 0.0}}, {"a": 1.0}),
        ({"a": {}}, {"unknown": 1.0}),
        ({"a": {}}, {"a": 0.0}),
    ],
)
def test_rejects_malformed_graph_or_seeds(graph, seeds) -> None:
    with pytest.raises(ValueError):
        _weighted_ppr_reference(graph, seeds)


def test_scope_consent_revocation_and_source_status_in_synthetic_view() -> None:
    nodes = (
        _ScopedNode("seed", "tenant-1", "user-1"),
        _ScopedNode("public", "tenant-1", "user-1"),
        _ScopedNode("revoked", "tenant-1", "user-1", consent_granted=False),
        _ScopedNode("other-user", "tenant-1", "user-2"),
        _ScopedNode("other-tenant", "tenant-2", "user-1"),
        _ScopedNode("source-denied", "tenant-1", "user-1"),
    )
    edges = (
        _ScopedEdge("seed", "public", "tenant-1", "user-1", 2.0),
        _ScopedEdge("seed", "revoked", "tenant-1", "user-1", 50.0),
        _ScopedEdge("seed", "other-user", "tenant-1", "user-1", 50.0),
        _ScopedEdge("seed", "other-tenant", "tenant-1", "user-1", 50.0),
        _ScopedEdge("seed", "source-denied", "tenant-1", "user-1", 20.0,
                    source_verified=False),
        _ScopedEdge("seed", "public", "tenant-1", "user-1", 2.0),
    )
    view = _synthetic_authorized_view(
        nodes, edges, tenant_id="tenant-1", user_id="user-1",
    )
    assert set(view) == {"seed", "public", "source-denied"}
    assert view["seed"] == {"public": 2.0}
    assert view["source-denied"] == {}
    scores = _weighted_ppr_reference(view, {"seed": 1.0}).scores
    assert "revoked" not in scores
    assert "other-user" not in scores
    assert "other-tenant" not in scores
    assert scores["source-denied"] == pytest.approx(0.0)


def test_deletion_rebuild_does_not_retain_removed_derived_scores() -> None:
    nodes = (
        _ScopedNode("seed", "tenant-1", "user-1"),
        _ScopedNode("leaf", "tenant-1", "user-1"),
    )
    edges = (_ScopedEdge("seed", "leaf", "tenant-1", "user-1"),)
    before = _weighted_ppr_reference(
        _synthetic_authorized_view(nodes, edges, tenant_id="tenant-1", user_id="user-1"),
        {"seed": 1.0},
    )
    after = _weighted_ppr_reference(
        _synthetic_authorized_view(
            (
                nodes[0],
                _ScopedNode("leaf", "tenant-1", "user-1", consent_granted=False),
            ),
            edges,
            tenant_id="tenant-1",
            user_id="user-1",
        ),
        {"seed": 1.0},
    )
    assert before.scores["leaf"] > 0
    assert "leaf" not in after.scores
    assert after.scores == {"seed": pytest.approx(1.0)}
