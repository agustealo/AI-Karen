"""Canonical memory graph adapter contracts and legacy import compatibility."""

from .base import GraphAdapter, GraphRepository
from .kuzu_adapter import KuzuGraphAdapter, KuzuGraphUnavailableError

__all__ = [
    "GraphAdapter",
    "GraphRepository",
    "KuzuGraphAdapter",
    "KuzuGraphUnavailableError",
]
