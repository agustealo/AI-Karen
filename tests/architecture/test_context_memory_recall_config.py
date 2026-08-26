from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "core"
    / "langgraph_orchestrator"
    / "contracts"
    / "orchestration_config.py"
)


def _config_type():
    spec = importlib.util.spec_from_file_location("context_recall_config_contract", CONFIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LangGraphOrchestrationConfig


def test_memory_recall_top_k_defaults_to_bounded_value() -> None:
    config_type = _config_type()
    config = config_type()
    assert config.memory_recall_top_k == 10
    assert config.validate() is True


def test_memory_recall_top_k_rejects_out_of_range_values() -> None:
    config_type = _config_type()
    with pytest.raises(ValueError, match="memory_recall_top_k"):
        config_type.from_dict({"memory_recall_top_k": 0})
    with pytest.raises(ValueError, match="memory_recall_top_k"):
        config_type.from_dict({"memory_recall_top_k": 51})


def test_memory_recall_top_k_accepts_valid_override() -> None:
    config_type = _config_type()
    config = config_type.from_dict({"memory_recall_top_k": 24})
    assert config.memory_recall_top_k == 24
