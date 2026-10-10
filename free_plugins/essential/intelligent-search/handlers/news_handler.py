import logging
from typing import Any, Dict, Optional

from .base import BaseWebSearchModeHandler

logger = logging.getLogger(__name__)


class NewsHandler(BaseWebSearchModeHandler):
    """
    News search intent handler.
    """

    MODE = "news"

    DEFAULTS: Dict[str, Any] = {
        "max_urls": 8,
        "depth": 1,
        "freshness_bias": 0.95,
        "require_citations": True,
        "query_strategy": "freshness_biased",
        "prefer_official_sources": False,
        "prefer_recent": True,
    }

    async def prepare(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        safe_context = context or {}
        normalized_query = self._normalize_query(query)
        can_execute, reason = self._can_execute(normalized_query)

        max_urls = self._coerce_positive_int(
            safe_context.get("max_urls"),
            self._read_manifest_setting("max_urls"),
            self.DEFAULTS["max_urls"],
        )
        depth = self._coerce_positive_int(
            safe_context.get("depth"),
            self._read_manifest_setting("depth"),
            self.DEFAULTS["depth"],
        )
        freshness_bias = self._coerce_float(
            safe_context.get("freshness_bias"),
            self._read_manifest_setting("freshness_bias"),
            self.DEFAULTS["freshness_bias"],
        )
        prefer_recent = self._coerce_bool(
            safe_context.get("prefer_recent"),
            self._read_manifest_setting("prefer_recent"),
            self.DEFAULTS["prefer_recent"],
        )
        prefer_official_sources = self._coerce_bool(
            safe_context.get("prefer_official_sources"),
            self._read_manifest_setting("prefer_official_sources"),
            self.DEFAULTS["prefer_official_sources"],
        )

        response = {
            "extension_id": self._get_manifest_id(),
            "extension_name": self._get_manifest_name(),
            "intent_type": "web_search",
            "mode": self.MODE,
            "query": normalized_query,
            "can_execute": can_execute,
            "reason": reason,
            "max_urls": max_urls,
            "depth": depth,
            "freshness_bias": freshness_bias,
            "require_citations": True,
            "query_strategy": "freshness_biased",
            "search_profile": {
                "prefer_recent": prefer_recent,
                "prefer_official_sources": prefer_official_sources,
                "prefer_news_publishers": True,
                "allow_forum_results": False,
            },
            "domain_policy": {
                "allowed_domains": self._normalize_list(
                    safe_context.get("allowed_domains")
                ),
                "blocked_domains": self._normalize_list(
                    safe_context.get("blocked_domains")
                ),
            },
            "time_policy": {
                "time_range": self._normalize_string(safe_context.get("time_range")),
                "published_after": safe_context.get("published_after"),
                "published_before": safe_context.get("published_before"),
            },
            "context_hints": self._extract_context_hints(safe_context),
            "telemetry": {
                "handler": self.__class__.__name__,
                "manifest_id": self._get_manifest_id(),
                "mode": self.MODE,
            },
        }

        self.logger.debug(
            "Prepared news search intent strategy",
            extra={
                "extension_id": response["extension_id"],
                "mode": response["mode"],
                "can_execute": response["can_execute"],
                "max_urls": response["max_urls"],
            },
        )

        return response

    async def execute(self, config: Dict[str, Any], query: str) -> Dict[str, Any]:
        prepared = dict(config or {})
        normalized_query = self._normalize_query(query or prepared.get("query", ""))

        if not prepared.get("query"):
            prepared["query"] = normalized_query

        if "can_execute" not in prepared or "reason" not in prepared:
            can_execute, reason = self._can_execute(normalized_query)
            prepared["can_execute"] = can_execute
            prepared["reason"] = reason

        prepared.setdefault("extension_id", self._get_manifest_id())
        prepared.setdefault("extension_name", self._get_manifest_name())
        prepared.setdefault("intent_type", "web_search")
        prepared.setdefault("mode", self.MODE)
        prepared.setdefault("max_urls", self.DEFAULTS["max_urls"])
        prepared.setdefault("depth", self.DEFAULTS["depth"])
        prepared.setdefault("freshness_bias", self.DEFAULTS["freshness_bias"])
        prepared.setdefault("require_citations", True)
        prepared.setdefault("query_strategy", "freshness_biased")
        prepared.setdefault(
            "search_profile",
            {
                "prefer_recent": self.DEFAULTS["prefer_recent"],
                "prefer_official_sources": self.DEFAULTS["prefer_official_sources"],
                "prefer_news_publishers": True,
                "allow_forum_results": False,
            },
        )
        prepared.setdefault(
            "domain_policy",
            {
                "allowed_domains": [],
                "blocked_domains": [],
            },
        )
        prepared.setdefault(
            "time_policy",
            {
                "time_range": None,
                "published_after": None,
                "published_before": None,
            },
        )

        return prepared
