"""Memory scoring public API.

Package-root imports are intentionally lazy so a caller can use one pure
scoring primitive without initializing logging, observability, NLP, or other
unrelated scoring services.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .ranking import MemoryRanker

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ContradictionScorer": (".contradiction_scoring", "ContradictionScorer"),
    "MemoryWorthinessScorer": (".memory_worthiness", "MemoryWorthinessScorer"),
    "ReinforcementScorer": (".reinforcement_scoring", "ReinforcementScorer"),
    "SemanticSignalScorer": (".semantic_signal_scorer", "SemanticSignalScorer"),
    "get_semantic_scorer": (".semantic_signal_scorer", "get_semantic_scorer"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "ContradictionScorer",
    "MemoryRanker",
    "MemoryWorthinessScorer",
    "ReinforcementScorer",
    "SemanticSignalScorer",
    "get_semantic_scorer",
]
