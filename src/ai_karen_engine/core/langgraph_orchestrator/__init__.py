"""LangGraph orchestration package.

This package is intentionally passive at import time. Concrete runtime objects
live in the module files and are loaded lazily on attribute access so package
imports do not bootstrap the full application stack.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "LangGraphOrchestrator",
    "LangGraphOrchestrationConfig",
    "create_orchestrator",
    "get_default_orchestrator",
    "set_default_orchestrator",
    "DecisionEngine",
    "LangGraphOrchestrationState",
]


def __getattr__(name: str) -> Any:
    if name in {
        "LangGraphOrchestrator",
        "LangGraphOrchestrationConfig",
        "create_orchestrator",
        "get_default_orchestrator",
        "set_default_orchestrator",
    }:
        module = import_module(
            "ai_karen_engine.core.langgraph_orchestrator.langgraph_orchestrator"
        )
        return getattr(module, name)

    if name == "DecisionEngine":
        module = import_module(
            "ai_karen_engine.core.langgraph_orchestrator.decision_engine"
        )
        return getattr(module, name)

    if name == "LangGraphOrchestrationState":
        module = import_module(
            "ai_karen_engine.core.langgraph_orchestrator.contracts"
        )
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

