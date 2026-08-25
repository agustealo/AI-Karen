import pytest


@pytest.mark.cognitive
def test_benchmark_support_layer_imports():
    from benchmarks.cognitive import contracts, builders, decision_model  # noqa: F401


@pytest.mark.cognitive
def test_cognitive_state_dataclass():
    from benchmarks.cognitive.builders import CognitiveState
    state = CognitiveState()
    assert state.claims == []
    assert state.deleted_ids == set()
