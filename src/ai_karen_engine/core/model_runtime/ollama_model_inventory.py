"""Canonical Ollama model inventory for the runtime and its API projections.

Ollama's native /api/tags response owns installed-model truth. The runtime
owns endpoint selection; routes may authorize caller-supplied URLs but must
not invoke one another or invent model IDs from persisted defaults.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider


def _get_field(option: Any, key: str) -> Any:
    if isinstance(option, Mapping):
        return option.get(key)
    return getattr(option, key, None)


def resolve_ollama_inventory_endpoint(
    *,
    saved_base_url: str | None,
    configured_base_url: str | None,
    runtime_source: str | None,
    runtime_options: Sequence[Any] = (),
) -> str | None:
    """Resolve the current configured endpoint, never a UI-constructed host.

    A saved endpoint takes precedence; otherwise use the selected, available
    runtime option before falling back to the provider registry endpoint.
    """
    if saved_base_url and saved_base_url.strip():
        return saved_base_url.strip()
    source = runtime_source or "host"
    option = next(
        (
            item for item in runtime_options
            if _get_field(item, "source") == source
            and _get_field(item, "available") is True
            and isinstance(_get_field(item, "base_url"), str)
            and _get_field(item, "base_url").strip()
        ),
        None,
    )
    return str(_get_field(option, "base_url")).strip() if option is not None else configured_base_url


async def discover_installed_ollama_models(base_url: str) -> list[str]:
    """Get exact installed model names from Ollama without synthetic fallbacks."""
    if not base_url or not base_url.strip():
        raise ValueError("Ollama inventory endpoint is not configured")

    def _read() -> list[str]:
        client = OllamaProvider(base_url=base_url, timeout=3, max_retries=0)
        return client.get_models()

    return await asyncio.to_thread(_read)
