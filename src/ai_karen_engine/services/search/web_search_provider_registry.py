"""
Web search provider registry.

Owns provider descriptors, availability, health, and canonical selection logic.
The search client delegates provider routing here instead of embedding
hardcoded fallback chains.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .web_search_defaults import build_provider_configs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebSearchProviderDescriptor:
    """
    Stable description of a web search provider.
    """

    provider_id: str
    capabilities: Sequence[str] = field(default_factory=tuple)
    locality: str = "external"
    requires_api_key: bool = False
    supports_time_filter: bool = False
    supports_structured_results: bool = False
    supported_filters: Sequence[str] = field(default_factory=tuple)
    rate_limit_metadata: Mapping[str, Any] = field(default_factory=dict)
    health: str = "unknown"
    config: Mapping[str, Any] = field(default_factory=dict)


WEB_SEARCH_CAPABILITIES: Dict[str, WebSearchProviderDescriptor] = {
    "web.search": WebSearchProviderDescriptor(
        provider_id="web.search",
        capabilities=("web.search",),
        locality="any",
        requires_api_key=False,
        supports_time_filter=True,
        supports_structured_results=True,
        supported_filters=("time_range",),
    ),
    "web.fetch.public": WebSearchProviderDescriptor(
        provider_id="web.fetch.public",
        capabilities=("web.fetch.public",),
        locality="external",
        requires_api_key=False,
        supports_time_filter=False,
        supports_structured_results=False,
        supported_filters=(),
    ),
    "web.scrape.public": WebSearchProviderDescriptor(
        provider_id="web.scrape.public",
        capabilities=("web.scrape.public",),
        locality="external",
        requires_api_key=False,
        supports_time_filter=False,
        supports_structured_results=True,
        supported_filters=(),
    ),
    "web.crawl.public": WebSearchProviderDescriptor(
        provider_id="web.crawl.public",
        capabilities=("web.crawl.public",),
        locality="external",
        requires_api_key=False,
        supports_time_filter=False,
        supports_structured_results=True,
        supported_filters=("max_pages", "max_depth"),
    ),
    "web.extract.structured": WebSearchProviderDescriptor(
        provider_id="web.extract.structured",
        capabilities=("web.extract.structured",),
        locality="any",
        requires_api_key=False,
        supports_time_filter=False,
        supports_structured_results=True,
        supported_filters=(),
    ),
    "web.screenshot": WebSearchProviderDescriptor(
        provider_id="web.screenshot",
        capabilities=("web.screenshot",),
        locality="external",
        requires_api_key=False,
        supports_time_filter=False,
        supports_structured_results=False,
        supported_filters=(),
    ),
}


class WebSearchProviderRegistry:
    """
    Canonical registry for web search providers.

    Responsibilities:
    - Store provider descriptors and runtime config.
    - Track availability and health.
    - Select providers based on requested provider, policy, health, and capability fit.
    """

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        descriptors: Optional[Dict[str, WebSearchProviderDescriptor]] = None,
    ) -> None:
        self.settings = settings or {}
        self.descriptors = dict(descriptors or self._default_descriptors())
        self._configs = build_provider_configs(self.settings)

    def _default_descriptors(self) -> Dict[str, WebSearchProviderDescriptor]:
        return {
            "duckduckgo": WebSearchProviderDescriptor(
                provider_id="duckduckgo",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=False,
                supports_structured_results=False,
                supported_filters=(),
                config={},
            ),
            "searxng": WebSearchProviderDescriptor(
                provider_id="searxng",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=True,
                supports_structured_results=True,
                supported_filters=("time_range", "categories", "safesearch"),
                config={},
            ),
            "brave_search": WebSearchProviderDescriptor(
                provider_id="brave_search",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=True,
                supports_time_filter=False,
                supports_structured_results=True,
                supported_filters=(),
                config={},
            ),
            "brave_search_free": WebSearchProviderDescriptor(
                provider_id="brave_search_free",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=False,
                supports_structured_results=False,
                supported_filters=(),
                config={},
            ),
            "tavily": WebSearchProviderDescriptor(
                provider_id="tavily",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=True,
                supports_time_filter=True,
                supports_structured_results=True,
                supported_filters=("time_range",),
                config={},
            ),
            "mojeek": WebSearchProviderDescriptor(
                provider_id="mojeek",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=False,
                supports_structured_results=False,
                supported_filters=(),
                config={},
            ),
            "wikipedia": WebSearchProviderDescriptor(
                provider_id="wikipedia",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=False,
                supports_structured_results=False,
                supported_filters=(),
                config={},
            ),
            "startpage": WebSearchProviderDescriptor(
                provider_id="startpage",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=False,
                supports_time_filter=False,
                supports_structured_results=False,
                supported_filters=(),
                config={},
            ),
            "google_custom_search": WebSearchProviderDescriptor(
                provider_id="google_custom_search",
                capabilities=("web.search",),
                locality="external",
                requires_api_key=True,
                supports_time_filter=True,
                supports_structured_results=True,
                supported_filters=("time_range",),
                config={},
            ),
        }

    def get_descriptor(self, provider_id: str) -> Optional[WebSearchProviderDescriptor]:
        return self.descriptors.get(provider_id)

    def get_config(self, provider_id: str) -> Dict[str, Any]:
        return dict(self._configs.get(provider_id, {}))

    def is_enabled(self, provider_id: str) -> bool:
        config = self.get_config(provider_id)
        return bool(config.get("enabled", False))

    def set_health(self, provider_id: str, health: str) -> None:
        descriptor = self.descriptors.get(provider_id)
        if descriptor is not None:
            self.descriptors[provider_id] = WebSearchProviderDescriptor(
                **{
                    **descriptor.__dict__,
                    "health": health,
                }
            )

    def select_provider(
        self,
        requested: Optional[str] = None,
        *,
        policy_permitted: Optional[Sequence[str]] = None,
        capability_required: Optional[Sequence[str]] = None,
        healthy_only: bool = True,
    ) -> Optional[str]:
        """
        Select the best provider for the request.

        Selection order:
        1. Requested provider, if permitted, configured, healthy, and capable.
        2. First configured, healthy, capable provider from policy_permitted.
        3. First configured, healthy, capable provider overall.
        """
        permitted = set(policy_permitted or self.descriptors.keys())
        capability_required = tuple(capability_required or ())

        candidates = []
        for provider_id in self.descriptors:
            config = self.get_config(provider_id)
            if not config.get("enabled", False):
                continue
            if provider_id not in permitted:
                continue
            descriptor = self.descriptors[provider_id]
            if healthy_only and descriptor.health in {"unhealthy", "degraded"}:
                continue
            if capability_required:
                if not all(cap in descriptor.capabilities for cap in capability_required):
                    continue
            candidates.append(provider_id)

        if not candidates:
            return None

        if requested and requested in candidates:
            descriptor = self.descriptors.get(requested)
            if descriptor and (not healthy_only or descriptor.health not in {"unhealthy", "degraded"}):
                return requested

        return candidates[0]

    def sorted_enabled(self, policy_permitted: Optional[Sequence[str]] = None) -> List[str]:
        """
        Return enabled providers sorted by configured priority.
        """
        permitted = set(policy_permitted or self.descriptors.keys())

        def sort_key(provider_id: str) -> int:
            config = self.get_config(provider_id)
            return int(config.get("priority", 0) or 0)

        return sorted(
            [
                provider_id
                for provider_id in self.descriptors
                if provider_id in permitted and self.is_enabled(provider_id)
            ],
            key=sort_key,
            reverse=True,
        )
