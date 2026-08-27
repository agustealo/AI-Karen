import pytest

from ai_karen_engine.core.memory.graph.config import LeanGraphConfig


def test_leangraph_config_defaults_to_postgres(monkeypatch):
    monkeypatch.delenv("KARI_GRAPH_BACKEND", raising=False)
    cfg = LeanGraphConfig.from_env()
    assert cfg.graph_backend == "postgres"
    assert cfg.graph_max_entities_per_event > 0


def test_leangraph_config_rejects_retired_kuzu():
    cfg = LeanGraphConfig(graph_backend="kuzu")
    with pytest.raises(ValueError, match="kuzu is retired"):
        cfg.validate()


def test_leangraph_config_allows_explicit_in_memory_for_tests():
    cfg = LeanGraphConfig(graph_backend="in_memory")
    cfg.validate()
