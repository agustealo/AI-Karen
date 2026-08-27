import pytest

from ai_karen_engine.core.memory.associative.spreading_activation import (
    AssociationGraph,
    SpreadingActivation,
)


def test_add_association_deduplicates_source_neighbors():
    graph = AssociationGraph()
    graph.add_association("a", "b")
    graph.add_association("a", "b")
    assert graph.edges["a"] == ["b"]


def test_get_neighbors_honors_depth_and_cycles():
    graph = AssociationGraph(
        edges={
            "a": ["b"],
            "b": ["c"],
            "c": ["a", "d"],
        }
    )

    assert graph.get_neighbors("a", depth=0) == set()
    assert graph.get_neighbors("a", depth=1) == {"b"}
    assert graph.get_neighbors("a", depth=2) == {"b", "c"}
    assert graph.get_neighbors("a", depth=3) == {"b", "c", "d"}


def test_spreading_activation_respects_decay_and_depth():
    graph = AssociationGraph(
        edges={"m1": ["m2"], "m2": ["m3"], "m3": ["m4"]},
        concept_index={"seed": ["m1"]},
    )
    activation = SpreadingActivation(
        graph,
        activation_decay=0.5,
        max_propagation_depth=2,
    )

    scores = activation.activate(["seed"], context={"tenant_id": "t1"})

    assert scores["m1"] == 1.0
    assert scores["m2"] == 0.5
    assert scores["m3"] == 0.25
    assert "m4" not in scores


def test_spreading_activation_validates_bounds():
    with pytest.raises(ValueError, match="activation_decay"):
        SpreadingActivation(AssociationGraph(), activation_decay=1.1)
    with pytest.raises(ValueError, match="max_propagation_depth"):
        SpreadingActivation(AssociationGraph(), max_propagation_depth=-1)
