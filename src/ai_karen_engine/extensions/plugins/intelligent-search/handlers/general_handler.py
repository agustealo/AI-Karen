import logging
import time
from typing import Any, Dict, Optional

from .base import BaseWebSearchModeHandler

logger = logging.getLogger(__name__)


class GeneralHandler(BaseWebSearchModeHandler):
    """
    General web search intent handler.

    Responsibilities:
    - Prepare a normalized retrieval strategy for general web search
    - Return structured intent payloads for orchestrator/runtime use
    - Do NOT perform crawling, ranking, or answer generation
    """

    MODE = "general"

    DEFAULTS: Dict[str, Any] = {
        "max_urls": 5,
        "depth": 1,
        "freshness_bias": 0.3,
        "require_citations": True,
        "query_strategy": "broad",
        "prefer_official_sources": False,
        "prefer_recent": False,
        "allow_forum_results": True,
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
        allow_forum_results = self._coerce_bool(
            safe_context.get("allow_forum_results"),
            self._read_manifest_setting("allow_forum_results"),
            self.DEFAULTS["allow_forum_results"],
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
            "query_strategy": "broad",
            "search_profile": {
                "prefer_recent": prefer_recent,
                "prefer_official_sources": prefer_official_sources,
                "prefer_news_publishers": False,
                "allow_forum_results": allow_forum_results,
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
            "Prepared general web search intent strategy",
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
        prepared.setdefault("query_strategy", "broad")
        prepared.setdefault(
            "search_profile",
            {
                "prefer_recent": self.DEFAULTS["prefer_recent"],
                "prefer_official_sources": self.DEFAULTS["prefer_official_sources"],
                "prefer_news_publishers": False,
                "allow_forum_results": self.DEFAULTS["allow_forum_results"],
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

        # Extract crawl options from context
        crawl_options = prepared.get("crawl", {})

        # Check if crawl is enabled
        crawl_enabled = crawl_options.get("enabled", False)

        # Perform actual web search
        client = self._get_search_client()
        if not client:
            self.logger.warning(
                "Web search client not initialized",
                extra={"handler": self.__class__.__name__},
            )
            prepared["error"] = "Search client not initialized"
            prepared["sources"] = []
            return prepared

        try:
            search_start_time = time.time()

            max_results = prepared.get("max_urls", self.DEFAULTS["max_urls"])
            time_range = prepared.get("time_policy", {}).get("time_range")

            async with client:
                search_response = await client.search(
                    query=normalized_query,
                    max_results=max_results,
                    time_range=time_range,
                )

            search_time = time.time() - search_start_time

            if search_response.error:
                prepared["error"] = search_response.error
                prepared["sources"] = []
                self.logger.warning(
                    f"Web search failed: {search_response.error}",
                    extra={
                        "query": normalized_query,
                        "provider": search_response.provider,
                        "error": search_response.error,
                    },
                )
            else:
                # Convert search results to the format expected by frontend
                sources = [
                    {
                        "title": result.title,
                        "url": result.url,
                        "snippet": result.snippet,
                        "content": result.content,
                        "publishedDate": result.published_date,
                    }
                    for result in search_response.results
                ]

                # If crawl is enabled, use Crawl4AI to extract full content
                if crawl_enabled and sources:
                    sources = await self._crawl_sources(
                        sources=sources,
                        crawl_options=crawl_options,
                    )

                prepared["sources"] = sources
                prepared["results"] = prepared.get("results", [])
                prepared["extractedData"] = None
                prepared["provider"] = search_response.provider
                prepared["total_results"] = search_response.total_results
                prepared["search_time"] = search_time

                # Ensure diagnostic fields are present for UI counters
                diagnostics = {
                    "mode": self.MODE,
                    "sourceCount": len(prepared["sources"]),
                    "urlsFound": len(search_response.results),
                    "latencyMs": int(search_time * 1000),
                    "degraded": False,
                }

                # Add crawl diagnostics if crawl was enabled
                if crawl_enabled:
                    diagnostics["pagesCrawled"] = len([s for s in sources if s.get("content")])
                    diagnostics["chunksProduced"] = diagnostics["pagesCrawled"]

                    # Add crawl metadata
                    prepared["crawl"] = {
                        "enabled": True,
                        "engine": "crawl4ai",
                        "status": "ok",
                        "pages_requested": len(search_response.results),
                        "pages_succeeded": diagnostics["pagesCrawled"],
                        "pages_failed": diagnostics["urlsFound"] - diagnostics["pagesCrawled"],
                        "latency_ms": diagnostics["latencyMs"],
                        "capabilities": {
                            "screenshot": crawl_options.get("capture_screenshot", False),
                            "structured_css_extraction": bool(crawl_options.get("structured_schema")),
                        },
                        "degraded": diagnostics["pagesCrawled"] < diagnostics["urlsFound"],
                        "degradation_reason": "partial_crawl" if diagnostics["pagesCrawled"] < diagnostics["urlsFound"] else None,
                    }
                else:
                    diagnostics["pagesCrawled"] = 0
                    diagnostics["chunksProduced"] = 0

                prepared["diagnostics"] = diagnostics

                self.logger.info(
                    f"Web search completed",
                    extra={
                        "query": normalized_query,
                        "provider": search_response.provider,
                        "results_count": len(search_response.results),
                        "total_results": search_response.total_results,
                        "crawl_enabled": crawl_enabled,
                        "pages_crawled": diagnostics["pagesCrawled"],
                    },
                )

        except Exception as e:
            prepared["error"] = str(e)
            prepared["sources"] = []
            self.logger.error(
                f"Web search exception: {e}",
                exc_info=True,
                extra={"query": normalized_query},
            )

        return prepared

    async def _crawl_sources(
        self, sources: list, crawl_options: Dict[str, Any]
    ) -> list:
        """
        Use Crawl4AI to extract full content from source URLs.

        Args:
            sources: List of source dictionaries with URL
            crawl_options: Crawl4AI configuration options

        Returns:
            Updated sources with full content
        """
        try:
            from ai_karen_engine.integrations.web.crawl4ai_integration import (
                Crawl4AIIntegration,
            )
        except ImportError:
            self.logger.warning("Crawl4AI not available, returning sources as-is")
            return sources

        # Extract URLs from sources
        urls = [s.get("url") for s in sources if s.get("url")]

        if not urls:
            return sources

        # Configure Crawl4AI options
        crawl_config = {
            "headless": True,
            "timeout_seconds": 45.0,
            "bypass_cache": not crawl_options.get("use_cache", True),
            "include_screenshot": crawl_options.get("capture_screenshot", False),
            "include_cleaned_html": crawl_options.get("extract_cleaned_html", False),
            "max_pages": crawl_options.get("max_pages", len(urls)),
        }

        # Build extraction strategy if schema is provided
        extraction_strategy = None
        schema = crawl_options.get("structured_schema")
        if schema:
            try:
                import json

                schema_dict = json.loads(schema)
                extraction_strategy = {
                    "type": "llm",
                    "schema": schema_dict,
                    "instruction": "Extract structured data according to the schema",
                }
            except json.JSONDecodeError:
                self.logger.warning("Invalid JSON in structured schema, ignoring")

        # Build wait selector
        wait_for_selector = crawl_options.get("wait_for_selector")

        # Initialize Crawl4AI
        try:
            integration = Crawl4AIIntegration(**crawl_config)
        except Exception as e:
            self.logger.error(f"Failed to initialize Crawl4AI: {e}")
            return sources

        # Crawl URLs
        crawl_results = {}
        try:
            results = await integration.fetch_many(
                urls=urls,
                bypass_cache=crawl_config.get("bypass_cache", False),
                timeout_seconds=crawl_config.get("timeout_seconds", 45.0),
            )

            # Map results by URL
            for result in results:
                if result.success and result.markdown:
                    crawl_results[result.url] = {
                        "content": result.markdown,
                        "text": result.text,
                        "markdown": result.markdown,
                        "links": result.links,
                        "media": result.media,
                        "success": True,
                    }
                elif result.error:
                    crawl_results[result.url] = {
                        "success": False,
                        "error": result.error,
                    }

        except Exception as e:
            self.logger.error(f"Crawl4AI fetch failed: {e}", exc_info=True)

        # Update sources with crawled content
        updated_sources = []
        for source in sources:
            url = source.get("url")
            if url and url in crawl_results:
                crawl_data = crawl_results[url]
                if crawl_data.get("success"):
                    source["content"] = crawl_data.get("content") or crawl_data.get("text")
                    source["markdown"] = crawl_data.get("markdown")
                    source["links"] = crawl_data.get("links", [])
                    source["media"] = crawl_data.get("media", {})
                    source["crawl_success"] = True
                else:
                    source["crawl_success"] = False
                    source["crawl_error"] = crawl_data.get("error", "Unknown error")
            else:
                source["crawl_success"] = False
                source["crawl_error"] = "URL not crawled"
            updated_sources.append(source)

        return updated_sources
