"""Compatibility adapter for canonical web-search configuration.

Runtime provider defaults live in ai_karen_engine.config.web_search.
Keep this module only for stable imports while callers migrate.
"""

from ai_karen_engine.config.web_search import (
    DEFAULT_PROVIDER_CONFIGS,
    DEFAULT_SEARXNG_INSTANCES,
    build_provider_configs,
)

__all__ = [
    "DEFAULT_PROVIDER_CONFIGS",
    "DEFAULT_SEARXNG_INSTANCES",
    "build_provider_configs",
]
