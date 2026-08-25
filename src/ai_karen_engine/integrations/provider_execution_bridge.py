"""Composition bridge from concrete integrations into the Core execution port.

This module is intentionally outside ``core``. Core owns provider selection and
the execution contract; integrations only construct the concrete provider that
Core has already selected.
"""
from __future__ import annotations

from typing import Any

from ai_karen_engine.core.model_runtime.provider_execution import (
    register_provider_factory,
)


def _provider_factory(provider_id: str, **kwargs: Any) -> Any:
    """Construct a concrete provider without making Core import integrations."""
    from ai_karen_engine.integrations.llm_registry import get_provider

    clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    return get_provider(provider_id, **clean_kwargs)


def register_provider_execution_bridge(*, replace: bool = False) -> None:
    """Register the integration-backed provider factory at application bootstrap."""
    register_provider_factory(_provider_factory, replace=replace)


__all__ = ["register_provider_execution_bridge"]
