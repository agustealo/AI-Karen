from __future__ import annotations

import pytest

from ai_karen_engine.core.langgraph_orchestrator.contracts.orchestration_config import (
    LangGraphOrchestrationConfig,
)


def test_memory_recall_top_k_defaults_to_bounded_value() -> None:
    config = LangGraphOrchestrationConfig()
    assert config.memory_recall_top_k == 10
    assert config.validate() is True


def test_memory_recall_top_k_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="memory_recall_top_k"):
        LangGraphOrchestrationConfig.from_dict({"memory_recall_top_k": 0})
    with pytest.raises(ValueError, match="memory_recall_top_k"):
        LangGraphOrchestrationConfig.from_dict({"memory_recall_top_k": 51})


def test_memory_recall_top_k_accepts_valid_override() -> None:
    config = LangGraphOrchestrationConfig.from_dict({"memory_recall_top_k": 24})
    assert config.memory_recall_top_k == 24
