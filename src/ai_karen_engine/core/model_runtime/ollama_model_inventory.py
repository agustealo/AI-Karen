"""Pure canonical selection of the configured Ollama runtime endpoint.

Ollama's native /api/tags adapter lives in integrations, and the Core never
imports that concrete adapter. API projections reuse this selection policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any



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
        (item for item in runtime_options if _get_field(item, "source") == source),
        None,
    )
    if option is not None:
        url = _get_field(option, "base_url")
        return (
            url.strip()
            if _get_field(option, "available") is True
            and isinstance(url, str) and url.strip()
            else None
        )
    # Do not silently switch from an unavailable selected runtime to
    # another Ollama installation with a different model inventory.
    if runtime_options:
        return None
    return configured_base_url
