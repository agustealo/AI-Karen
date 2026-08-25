from __future__ import annotations

from .contracts import EngineHealth, ExpressionResult, ExpressionTask

__all__ = [
    "EngineHealth",
    "ExpressionGateway",
    "ExpressionResult",
    "ExpressionTask",
]


def __getattr__(name: str):
    """Lazily expose runtime expression services from the package root.

    Pure contracts must not initialize routing, logging, observability, provider,
    or runtime state merely because ``ai_karen_engine.core.expression`` is
    imported.
    """
    if name == "ExpressionGateway":
        from .gateway import ExpressionGateway

        return ExpressionGateway
    raise AttributeError(name)
