"""Core-owned provider execution boundary.

The AI machine owns *when* and *which* provider executes, but it must never
import concrete integration/provider implementations.  Outer composition layers
register a factory here at startup.  Core consumers resolve provider instances
through this port only.
"""
from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProviderExecutionPort(Protocol):
    """Minimal provider surface consumed by Core expression engines.

    Concrete providers may expose sync or async generation methods.  The
    expression engines intentionally perform capability detection so adapters
    remain backwards compatible while provider implementations migrate toward a
    single typed execution contract.
    """

    model: Any


ProviderFactory = Callable[..., ProviderExecutionPort | None]


class ProviderExecutionRegistry:
    """Process-local registry for provider construction adapters.

    This registry contains factories supplied by the application composition
    edge.  It deliberately contains no provider discovery, secrets, SDK imports,
    plugin loading, or integration-specific behavior.
    """

    def __init__(self) -> None:
        self._factory: ProviderFactory | None = None
        self._lock = RLock()

    def register_factory(self, factory: ProviderFactory) -> None:
        """Install the application-level provider factory."""
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        with self._lock:
            self._factory = factory

    def clear_factory(self) -> None:
        """Remove the active factory, primarily for tests and controlled reloads."""
        with self._lock:
            self._factory = None

    def is_configured(self) -> bool:
        with self._lock:
            return self._factory is not None

    def create_provider(self, provider_id: str, **kwargs: Any) -> ProviderExecutionPort | None:
        """Construct a provider through the registered outer-layer factory."""
        with self._lock:
            factory = self._factory
        if factory is None:
            return None
        return factory(provider_id, **kwargs)


_registry = ProviderExecutionRegistry()


def get_provider_execution_registry() -> ProviderExecutionRegistry:
    """Return the canonical process-local provider execution registry."""
    return _registry


def register_provider_factory(factory: ProviderFactory) -> None:
    """Register an outer-layer provider factory with the Core execution port."""
    _registry.register_factory(factory)


__all__ = [
    "ProviderExecutionPort",
    "ProviderExecutionRegistry",
    "ProviderFactory",
    "get_provider_execution_registry",
    "register_provider_factory",
]
