"""
Default web search provider configurations.

This module owns canonical defaults for search providers so that
no provider-specific hardcoding lives inside the search client.
"""

from typing import Any, Dict, List, Optional, Sequence


DEFAULT_SEARXNG_INSTANCES: List[str] = [
    "https://searxng.site",
    "https://searx.be",
    "https://searxng.nicfab.eu",
    "https://search.ononoki.org",
    "https://priv.au",
    "https://searx.work",
    "https://searx.ctis.me",
    "https://searx.sethforprivacy.com",
    "https://searx.nakostu.me",
    "https://duskrose.com",
    "https://searx.prvcy.eu",
    "https://search.disroot.org",
]


DEFAULT_PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "duckduckgo": {
        "enabled": True,
        "priority": 100,
    },
    "searxng": {
        "enabled": True,
        "priority": 95,
        "instances": DEFAULT_SEARXNG_INSTANCES,
    },
    "brave_search": {
        "enabled": False,
        "priority": 92,
        "api_url": "https://api.search.brave.com/res/v1/web/search",
    },
    "brave_search_free": {
        "enabled": True,
        "priority": 91,
    },
    "tavily": {
        "enabled": False,
        "priority": 90,
        "api_url": "https://api.tavily.com/search",
    },
    "mojeek": {
        "enabled": True,
        "priority": 88,
    },
    "wikipedia": {
        "enabled": True,
        "priority": 85,
    },
    "startpage": {
        "enabled": True,
        "priority": 87,
    },
    "google_custom_search": {
        "enabled": False,
        "priority": 80,
        "api_url": "https://www.googleapis.com/customsearch/v1",
    },
}


def build_provider_configs(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Build provider configs by merging defaults with caller settings.

    Caller settings take precedence over defaults.
    """
    safe_settings = settings or {}
    merged = {
        name: dict(config)
        for name, config in DEFAULT_PROVIDER_CONFIGS.items()
    }

    search_settings = safe_settings.get("search", safe_settings)
    if not isinstance(search_settings, dict):
        return merged

    for name, override in search_settings.items():
        if not isinstance(override, dict):
            continue
        if name not in merged:
            merged[name] = {}
        merged[name].update(override)

    return merged
