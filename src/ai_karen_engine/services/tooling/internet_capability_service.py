"""
Internet Capability Service.

Karen-grade live internet intelligence pipeline.

Responsibilities:
- Validate and normalize a live-search request.
- Enforce prompt-first retrieval planning.
- Use centralized search/crawl clients instead of brittle plugin imports.
- Execute search, crawl, rank, citation, and diagnostics.
- Return a stable, UI-safe, orchestrator-safe response contract.
- Preserve graceful degraded behavior when search/crawl providers fail.

This service does NOT:
- Decide final assistant wording.
- Bypass RBAC.
- Directly call LLM providers.
- Persist chat messages.
- Own route-level HTTP concerns.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from prometheus_client import Counter, Histogram

from ..search.search_query_planner import SearchQueryPlanner
from ..search.search_result_processor import SearchResultProcessor
from ..search.web_search_provider_registry import WebSearchProviderRegistry
from ...integrations.web.crawl4ai_integration import Crawl4AIIntegration

logger = logging.getLogger(__name__)


INTERNET_SEARCH_REQUESTS = Counter(
    "karen_internet_capability_requests_total",
    "Total internet capability requests.",
    ["mode", "status", "degraded"],
)

INTERNET_SEARCH_LATENCY = Histogram(
    "karen_internet_capability_latency_seconds",
    "Internet capability request latency in seconds.",
    ["mode", "degraded"],
)

INTERNET_SEARCH_SOURCES = Histogram(
    "karen_internet_capability_sources_count",
    "Number of live sources returned by internet capability.",
    ["mode", "degraded"],
)


@dataclass(frozen=True)
class InternetExecutionContext:
    """
    Runtime context supplied by orchestrator/plugin layer.

    user_id/tenant_id/session_id are optional here because this capability can be
    used by admin diagnostics and internal workers, but callers that have identity
    context should always provide it.
    """

    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = "internet_capability"
    role: str = "user"
    permissions: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InternetSearchRequest:
    """
    Stable internal request model.

    The API/plugin layer may pass dictionaries, but this service normalizes to
    this model before executing.
    """

    query: str
    mode: Optional[str] = None
    requested_mode: Optional[str] = None
    max_urls: Optional[int] = None
    depth: Optional[int] = None
    freshness_bias: Optional[float] = None
    query_strategy: Optional[str] = None
    prefer_recent: Optional[bool] = None
    prefer_official_sources: Optional[bool] = None
    allow_forum_results: Optional[bool] = None
    allowed_domains: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None
    time_range: Optional[str] = None
    published_after: Optional[str] = None
    published_before: Optional[str] = None
    bypass_cache: bool = False
    timeout_seconds: float = 30.0
    crawl_concurrency: int = 5
    crawl_enabled: bool = False
    crawl_max_pages: Optional[int] = None
    crawl_max_depth: Optional[int] = None
    sources: Optional[List[str]] = None
    content_limits: Optional[Dict[str, Any]] = None
    extraction: Optional[Dict[str, Any]] = None

    @classmethod
    def from_payload(
        cls,
        query: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> "InternetSearchRequest":
        safe_payload = dict(payload or {})
        normalized_query = " ".join((query or "").split())

        if not normalized_query:
            raise ValueError("Internet search query cannot be empty.")

        max_urls = safe_payload.get("max_urls")
        if max_urls is not None:
            max_urls = max(1, min(int(max_urls), 25))

        crawl_concurrency = safe_payload.get("crawl_concurrency", 5)
        crawl_concurrency = max(1, min(int(crawl_concurrency), 10))

        timeout_seconds = safe_payload.get("timeout_seconds", 30.0)
        timeout_seconds = max(3.0, min(float(timeout_seconds), 90.0))

        return cls(
            query=normalized_query,
            mode=safe_payload.get("mode"),
            requested_mode=safe_payload.get("requested_mode"),
            max_urls=max_urls,
            depth=safe_payload.get("depth"),
            freshness_bias=safe_payload.get("freshness_bias"),
            query_strategy=safe_payload.get("query_strategy"),
            prefer_recent=safe_payload.get("prefer_recent"),
            prefer_official_sources=safe_payload.get("prefer_official_sources"),
            allow_forum_results=safe_payload.get("allow_forum_results"),
            allowed_domains=_normalize_domain_list(safe_payload.get("allowed_domains")),
            blocked_domains=_normalize_domain_list(safe_payload.get("blocked_domains")),
            time_range=safe_payload.get("time_range"),
            published_after=safe_payload.get("published_after"),
            published_before=safe_payload.get("published_before"),
            bypass_cache=bool(safe_payload.get("bypass_cache", False)),
            timeout_seconds=timeout_seconds,
            crawl_concurrency=crawl_concurrency,
            crawl_enabled=bool(safe_payload.get("crawl", {}).get("enabled", False) if isinstance(safe_payload.get("crawl"), dict) else safe_payload.get("crawl_enabled", False)),
            crawl_max_pages=safe_payload.get("crawl", {}).get("max_pages") if isinstance(safe_payload.get("crawl"), dict) else safe_payload.get("crawl_max_pages"),
            crawl_max_depth=safe_payload.get("crawl", {}).get("max_depth") if isinstance(safe_payload.get("crawl"), dict) else safe_payload.get("crawl_max_depth"),
            sources=safe_payload.get("sources"),
            content_limits=safe_payload.get("content_limits"),
            extraction=safe_payload.get("extraction"),
        )

    def strategy_overrides(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {
            "max_urls": self.max_urls,
            "depth": self.depth,
            "freshness_bias": self.freshness_bias,
            "query_strategy": self.query_strategy,
            "prefer_recent": self.prefer_recent,
            "prefer_official_sources": self.prefer_official_sources,
            "allow_forum_results": self.allow_forum_results,
            "allowed_domains": self.allowed_domains,
            "blocked_domains": self.blocked_domains,
            "time_range": self.time_range,
            "published_after": self.published_after,
            "published_before": self.published_before,
            "crawl_enabled": self.crawl_enabled,
            "crawl_max_pages": self.crawl_max_pages,
            "crawl_max_depth": self.crawl_max_depth,
            "sources": self.sources,
            "content_limits": self.content_limits,
        }
        return {key: value for key, value in values.items() if value is not None}


class SearchResultItem(Protocol):
    url: str


class SearchResponse(Protocol):
    results: Sequence[SearchResultItem]


class AsyncSearchClient(Protocol):
    async def __aenter__(self) -> "AsyncSearchClient":
        ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        ...

    async def search(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
    ) -> SearchResponse:
        ...


class InternetCapabilityService:
    """
    Karen internet intelligence engine.

    Canonical pipeline:
    1. Normalize request.
    2. Classify mode.
    3. Generate prompt-first query plan.
    4. Acquire candidate URLs.
    5. Crawl pages.
    6. Process, rank, denoise.
    7. Build citations/sources/results.
    8. Return stable diagnostics.
    """

    def __init__(
        self,
        *,
        planner: Optional[SearchQueryPlanner] = None,
        crawler: Optional[Crawl4AIIntegration] = None,
        processor: Optional[SearchResultProcessor] = None,
        search_client: Optional[AsyncSearchClient] = None,
        search_client_factory: Optional[Any] = None,
        provider_registry: Optional[WebSearchProviderRegistry] = None,
        default_max_urls: int = 5,
        max_expanded_queries: int = 2,
    ) -> None:
        self.planner = planner or SearchQueryPlanner()
        self.crawler = crawler or Crawl4AIIntegration()
        self.processor = processor or SearchResultProcessor()
        self.search_client = search_client
        self.search_client_factory = search_client_factory
        self.provider_registry = provider_registry or WebSearchProviderRegistry()
        self.default_max_urls = max(1, min(int(default_max_urls), 25))
        self.max_expanded_queries = max(1, min(int(max_expanded_queries), 5))

    async def execute(
        self,
        query: str,
        config_override: Optional[Dict[str, Any]] = None,
        context: Optional[InternetExecutionContext] = None,
    ) -> Dict[str, Any]:
        """
        Execute a full live internet intelligence cycle.

        This method intentionally preserves the old signature:
            execute(query, config_override=None)

        It adds optional context for RBAC/audit/telemetry integration without
        breaking existing plugin callers.
        """

        start_time = time.perf_counter()
        request = InternetSearchRequest.from_payload(query, config_override)
        execution_context = context or InternetExecutionContext()

        mode = self._resolve_mode(request)
        strategy = self._resolve_strategy(mode, request)
        expanded_queries = self._generate_queries(request.query)

        degraded = False
        warnings: List[str] = []
        urls: List[str] = []
        crawl_results: List[Dict[str, Any]] = []
        processed_chunks: List[Dict[str, Any]] = []

        logger.info(
            "internet_capability.started",
            extra={
                "correlation_id": execution_context.correlation_id,
                "request_id": execution_context.request_id,
                "user_id": execution_context.user_id,
                "tenant_id": execution_context.tenant_id,
                "mode": mode,
                "query": request.query,
            },
        )

        try:
            self._authorize(execution_context)

            urls = await asyncio.wait_for(
                self._get_relevant_urls(expanded_queries, strategy, request),
                timeout=request.timeout_seconds,
            )

            if not urls:
                degraded = True
                warnings.append("No URLs were returned by the search provider.")
                return self._build_response(
                    request=request,
                    mode=mode,
                    strategy=strategy,
                    expanded_queries=expanded_queries,
                    urls=[],
                    crawl_results=[],
                    processed_chunks=[],
                    start_time=start_time,
                    degraded=True,
                    warnings=warnings,
                    execution_context=execution_context,
                )

            crawl_results = await asyncio.wait_for(
                self._crawl_many(urls, request),
                timeout=request.timeout_seconds,
            )

            if not crawl_results:
                degraded = True
                warnings.append("Search returned URLs, but no pages could be crawled.")

            crawl_degraded = not getattr(self.crawler, "available", True)
            if crawl_degraded:
                degraded = True
                warnings.append(
                    "Crawl4AI is not installed or unavailable; content fetch is degraded."
                )
            else:
                # If Crawler is available, we can perform deeper extraction for specific modes
                if mode == "weather" and crawl_results:
                    logger.info("Performing structured weather extraction via Crawl4AI")
                    # Future: Implement schema-based extraction here if needed
                    pass

            processed_chunks = self.processor.process(crawl_results, request.query)

            return self._build_response(
                request=request,
                mode=mode,
                strategy=strategy,
                expanded_queries=expanded_queries,
                urls=urls,
                crawl_results=crawl_results,
                processed_chunks=processed_chunks,
                start_time=start_time,
                degraded=degraded,
                warnings=warnings,
                execution_context=execution_context,
            )

        except asyncio.TimeoutError:
            degraded = True
            warnings.append(
                f"Internet capability timed out after {request.timeout_seconds:.1f}s."
            )
            logger.warning(
                "internet_capability.timeout",
                extra={
                    "correlation_id": execution_context.correlation_id,
                    "request_id": execution_context.request_id,
                    "mode": mode,
                    "query": request.query,
                },
            )
            return self._build_response(
                request=request,
                mode=mode,
                strategy=strategy,
                expanded_queries=expanded_queries,
                urls=urls,
                crawl_results=crawl_results,
                processed_chunks=processed_chunks,
                start_time=start_time,
                degraded=True,
                warnings=warnings,
                execution_context=execution_context,
            )

        except PermissionError as exc:
            degraded = True
            warnings.append(str(exc))
            logger.warning(
                "internet_capability.permission_denied",
                extra={
                    "correlation_id": execution_context.correlation_id,
                    "request_id": execution_context.request_id,
                    "mode": mode,
                    "query": request.query,
                },
            )
            return self._build_response(
                request=request,
                mode=mode,
                strategy=strategy,
                expanded_queries=expanded_queries,
                urls=[],
                crawl_results=[],
                processed_chunks=[],
                start_time=start_time,
                degraded=True,
                warnings=warnings,
                execution_context=execution_context,
                status="permission_denied",
            )

        except Exception as exc:
            degraded = True
            warnings.append("Internet capability failed unexpectedly.")
            logger.exception(
                "internet_capability.failed",
                extra={
                    "correlation_id": execution_context.correlation_id,
                    "request_id": execution_context.request_id,
                    "mode": mode,
                    "query": request.query,
                    "error": str(exc),
                },
            )
            return self._build_response(
                request=request,
                mode=mode,
                strategy=strategy,
                expanded_queries=expanded_queries,
                urls=urls,
                crawl_results=crawl_results,
                processed_chunks=processed_chunks,
                start_time=start_time,
                degraded=True,
                warnings=warnings,
                execution_context=execution_context,
                status="error",
            )

    async def _get_relevant_urls(
        self,
        queries: Sequence[str],
        strategy: Mapping[str, Any],
        request: InternetSearchRequest,
    ) -> List[str]:
        """
        Fetch unique URLs from the configured search provider.

        This avoids importing plugin files directly. The caller should inject a
        first-class search client/factory from Karen config/bootstrap.
        """

        client = self._resolve_search_client()
        max_urls = int(strategy.get("max_urls") or request.max_urls or self.default_max_urls)
        max_urls = max(1, min(max_urls, 25))

        all_urls: List[str] = []

        for search_query in list(queries)[: self.max_expanded_queries]:
            try:
                async with client as active_client:
                    response = await active_client.search(
                        query=search_query,
                        max_results=max_urls,
                        time_range=strategy.get("time_range"),
                    )

                for result in getattr(response, "results", []) or []:
                    url = self._normalize_url(getattr(result, "url", None))
                    if not url:
                        continue

                    if self._is_url_allowed(url, strategy):
                        all_urls.append(url)

            except Exception as exc:
                logger.warning(
                    "internet_capability.search_query_failed",
                    extra={
                        "query": search_query,
                        "error": str(exc),
                    },
                )

        unique_urls = list(dict.fromkeys(all_urls))
        return unique_urls[:max_urls]

    async def _crawl_many(
        self,
        urls: Sequence[str],
        request: InternetSearchRequest,
    ) -> List[Dict[str, Any]]:
        """
        Crawl URLs using the configured crawler.

        Uses crawler.fetch_many when available. Falls back to bounded single-URL
        fetches for crawler implementations that only expose fetch_url.
        """

        if not urls:
            return []
            
        extraction_strategy = None
        if request.extraction and hasattr(self.crawler, "_build_extraction_strategy"):
            extraction_strategy = self.crawler._build_extraction_strategy(request.extraction)

        # Optimization: use fetch_many if available and no specialized extraction requested
        if not extraction_strategy and hasattr(self.crawler, "fetch_many"):
            results = await self.crawler.fetch_many(
                list(urls),
                bypass_cache=request.bypass_cache,
            )
            return self._normalize_crawl_results(results)

        semaphore = asyncio.Semaphore(request.crawl_concurrency)

        async def fetch_one(url: str) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    result = await self.crawler.fetch_url(
                        url,
                        bypass_cache=request.bypass_cache,
                        extraction_strategy=extraction_strategy,
                    )
                    if isinstance(result, dict):
                        return result
                except Exception as exc:
                    logger.warning(
                        "internet_capability.crawl_url_failed",
                        extra={"url": url, "error": str(exc)},
                    )
                return None

        fetched = await asyncio.gather(*(fetch_one(url) for url in urls))
        return [item for item in fetched if item]

    def _build_response(
        self,
        *,
        request: InternetSearchRequest,
        mode: str,
        strategy: Mapping[str, Any],
        expanded_queries: Sequence[str],
        urls: Sequence[str],
        crawl_results: Sequence[Dict[str, Any]],
        processed_chunks: Sequence[Dict[str, Any]],
        start_time: float,
        degraded: bool,
        warnings: Sequence[str],
        execution_context: InternetExecutionContext,
        status: str = "ok",
    ) -> Dict[str, Any]:
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        sources = self._build_sources(crawl_results)
        results = self._build_results(processed_chunks)
        citations = self._generate_citations(crawl_results, processed_chunks)
        diagnostics = self._build_diagnostics(
            mode=mode,
            strategy=strategy,
            execution_time_ms=execution_time_ms,
            urls_found=len(urls),
            pages_crawled=len(crawl_results),
            chunks_produced=len(processed_chunks),
            source_count=len(sources),
            degraded=degraded,
            warnings=list(warnings),
            status=status,
        )

        # Aggregate extracted data if multiple sources have it
        aggregated_extracted_data = {}
        for s in (sources or []):
            if s.get("extracted_data"):
                # If it's a list, we append it; if it's a dict, we merge it
                s_data = s["extracted_data"]
                if isinstance(s_data, list):
                    if "items" not in aggregated_extracted_data:
                        aggregated_extracted_data["items"] = []
                    aggregated_extracted_data["items"].extend(s_data)
                elif isinstance(s_data, dict):
                    aggregated_extracted_data.update(s_data)
                else:
                    if "raw" not in aggregated_extracted_data:
                        aggregated_extracted_data["raw"] = []
                    aggregated_extracted_data["raw"].append(s_data)

        # Merge top-level extraction data if present (e.g. from mode-specific logic)
        if request.extraction and "items" not in aggregated_extracted_data and not aggregated_extracted_data:
            # Check if any crawl results had it directly
            for r in crawl_results:
                if r.get("extracted_content"):
                    ec = r["extracted_content"]
                    if isinstance(ec, dict): aggregated_extracted_data.update(ec)
                    elif isinstance(ec, list):
                        aggregated_extracted_data.setdefault("items", []).extend(ec)

        response = {
            "query": request.query,
            "mode": mode,
            "status": status,
            "summary": self._build_summary(
                query=request.query,
                mode=mode,
                sources=sources,
                results=results,
                execution_time_ms=execution_time_ms,
                degraded=degraded,
                warnings=list(warnings),
            ),
            "sources": sources or [],
            "citations": citations or [],
            "results": results or [],
            "extractedData": aggregated_extracted_data or None,
            "insights": self._build_insights(
                mode=mode,
                sources=sources,
                results=results,
                urls_found=len(urls),
                pages_crawled=len(crawl_results),
                degraded=degraded,
            ),
            "diagnostics": diagnostics,
            "metadata": {
                "execution_time_ms": execution_time_ms,
                "urls_found": len(urls),
                "pages_crawled": len(crawl_results),
                "chunks_produced": len(processed_chunks),
                "mode": mode,
                "strategy_used": dict(strategy),
                "expanded_queries": list(expanded_queries)[:5],
                "source_count": len(sources),
                "degraded": degraded,
                "provider": self._provider_name(),
                "correlation_id": execution_context.correlation_id,
                "request_id": execution_context.request_id,
            },
            "provider": self._provider_name(),
            "liveSearch": { # NextJS UI prefers liveSearch camelCase often, keep both for compatibility
                "mode": mode,
                "query": request.query,
                "expanded_queries": list(expanded_queries)[:5],
                "urls": list(urls),
                "crawl_results": list(crawl_results),
                "processed_chunks": list(processed_chunks),
            },
            "live_search": {
                "mode": mode,
                "query": request.query,
                "expanded_queries": list(expanded_queries)[:5],
                "urls": list(urls),
                "crawl_results": list(crawl_results),
                "processed_chunks": list(processed_chunks),
            },
            "execution_time_ms": execution_time_ms,
        }

        degraded_label = str(bool(degraded)).lower()
        INTERNET_SEARCH_REQUESTS.labels(
            mode=mode,
            status=status,
            degraded=degraded_label,
        ).inc()
        INTERNET_SEARCH_LATENCY.labels(
            mode=mode,
            degraded=degraded_label,
        ).observe(execution_time_ms / 1000)
        INTERNET_SEARCH_SOURCES.labels(
            mode=mode,
            degraded=degraded_label,
        ).observe(len(sources))

        logger.info(
            "internet_capability.completed",
            extra={
                "correlation_id": execution_context.correlation_id,
                "request_id": execution_context.request_id,
                "mode": mode,
                "status": status,
                "degraded": degraded,
                "source_count": len(sources),
                "execution_time_ms": execution_time_ms,
            },
        )

        return response

    def _resolve_mode(self, request: InternetSearchRequest) -> str:
        requested = request.mode or request.requested_mode
        if requested:
            return str(requested).strip().lower()
        return str(self.planner.classify_mode(request.query)).strip().lower()

    def _resolve_strategy(
        self,
        mode: str,
        request: InternetSearchRequest,
    ) -> Dict[str, Any]:
        strategy = dict(self.planner.get_retrieval_strategy(mode) or {})
        strategy.update(request.strategy_overrides())

        if "max_urls" not in strategy or strategy["max_urls"] is None:
            strategy["max_urls"] = self.default_max_urls

        strategy["max_urls"] = max(1, min(int(strategy["max_urls"]), 25))
        return strategy

    def _generate_queries(self, query: str) -> List[str]:
        generated = self.planner.generate_queries(query) or [query]
        normalized = []
        for item in generated:
            value = " ".join(str(item or "").split())
            if value:
                normalized.append(value)
        return list(dict.fromkeys(normalized)) or [query]

    def _resolve_search_client(self) -> AsyncSearchClient:
        if self.search_client is not None:
            return self.search_client

        if self.search_client_factory is not None:
            client = self.search_client_factory()
            if client is None:
                raise RuntimeError("Configured search_client_factory returned None.")
            return client

        try:
            from ai_karen_engine.clients.web_search.client import WebSearchClient

            settings = {}
            if self.provider_registry is not None:
                settings = {
                    "search": {
                        name: self.provider_registry.get_config(name)
                        for name in self.provider_registry.descriptors
                    }
                }
            return WebSearchClient(settings=settings)
        except Exception as exc:
            raise RuntimeError(
                "No internet search client is configured. "
                "Inject search_client/search_client_factory or provider_registry."
            ) from exc

    def _authorize(self, context: InternetExecutionContext) -> None:
        """
        Capability-level RBAC guard.

        This is intentionally light because full RBAC belongs in the caller.
        Still, this protects direct service use.
        """

        permissions = set(context.permissions or [])
        role = (context.role or "user").lower()

        if role in {"admin", "system", "service"}:
            return

        if not permissions:
            return

        allowed = {
            "internet:search",
            "web:search",
            "capability:internet",
            "plugin:intelligent-search",
        }

        if permissions.isdisjoint(allowed):
            raise PermissionError("Internet search is not permitted for this context.")

    def _normalize_crawl_results(
        self,
        results: Any,
    ) -> List[Dict[str, Any]]:
        if not results:
            return []

        normalized: List[Dict[str, Any]] = []

        for item in results:
            if isinstance(item, dict):
                normalized.append(item)
                continue

            value = {
                "url": getattr(item, "url", ""),
                "final_url": getattr(item, "final_url", ""),
                "title": getattr(item, "title", ""),
                "markdown": getattr(item, "markdown", ""),
                "text": getattr(item, "text", ""),
                "html": getattr(item, "html", ""),
                "cleaned_html": getattr(item, "cleaned_html", ""),
                "links": getattr(item, "links", []) or [],
                "media": getattr(item, "media", {}) or {},
                "metadata": getattr(item, "metadata", {}) or {},
                "extracted_content": getattr(item, "extracted_content", None),
                "success": getattr(item, "success", True),
                "status_code": getattr(item, "status_code", None),
                "elapsed_ms": getattr(item, "elapsed_ms", 0.0),
            }
            normalized.append(value)

        return normalized

    def _generate_citations(
        self,
        crawl_results: Sequence[Dict[str, Any]],
        processed_chunks: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []

        cited_urls = set()
        for idx, result in enumerate(list(crawl_results)[:20]):
            url = result.get("url", "")
            normalized_url = self._normalize_url(url)
            if not normalized_url or normalized_url in cited_urls:
                continue

            cited_urls.add(normalized_url)

            metadata = result.get("metadata", {}) or {}
            title = (
                metadata.get("title")
                or metadata.get("og:title")
                or result.get("title")
                or urlparse(normalized_url).netloc
            )
            preview = result.get("text") or result.get("markdown") or ""

            citations.append(
                {
                    "id": f"citation_{len(citations)}",
                    "url": normalized_url,
                    "title": title,
                    "snippet": self._summarize_text(preview, 240),
                    "index": len(citations),
                    "metadata": {
                        "source": "web_search",
                        "domain": urlparse(normalized_url).netloc,
                    },
                }
            )

        if citations:
            return citations

        for idx, chunk in enumerate(list(processed_chunks)[:20]):
            url = self._normalize_url(chunk.get("url"))
            if not url or url in cited_urls:
                continue

            cited_urls.add(url)
            content = chunk.get("content", "") or ""

            citations.append(
                {
                    "id": f"citation_{idx}",
                    "url": url,
                    "title": self._chunk_title(content, url, idx),
                    "snippet": self._summarize_text(content, 240),
                    "index": idx,
                    "metadata": {
                        "source": "processed_chunk",
                        "domain": urlparse(url).netloc,
                    },
                }
            )

        return citations

    def _build_sources(
        self,
        crawl_results: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []
        seen_urls = set()

        for result in list(crawl_results)[:10]:
            url = self._normalize_url(result.get("url"))
            if not url or url in seen_urls:
                continue

            seen_urls.add(url)

            metadata = result.get("metadata", {}) or {}
            markdown = result.get("markdown", "") or ""
            text = result.get("text", "") or ""
            title = (
                metadata.get("title")
                or metadata.get("og:title")
                or result.get("title")
                or urlparse(url).netloc
            )
            preview_source = text or markdown

            sources.append(
                {
                    "id": f"source_{len(sources)}",
                    "url": url,
                    "title": title,
                    "domain": urlparse(url).netloc,
                    "snippet": self._summarize_text(preview_source, 220),
                    "content": self._summarize_text(preview_source, 1000),
                    "full_content": markdown,
                    "markdown": markdown,
                    "extracted_data": result.get("extracted_content"),
                    "publishedDate": metadata.get("published_date")
                    or metadata.get("date")
                    or metadata.get("article:published_time"),
                    "relevanceScore": round(max(0.0, 1.0 - (len(sources) * 0.08)), 2),
                    "links": result.get("links", []),
                    "media": result.get("media", {}),
                }
            )

        return sources

    def _build_results(
        self,
        processed_chunks: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for chunk in list(processed_chunks)[:12]:
            content = chunk.get("content", "") or ""
            url = self._normalize_url(chunk.get("url")) or ""

            results.append(
                {
                    "id": chunk.get("chunk_id", f"chunk_{len(results)}"),
                    "title": self._chunk_title(content, url, len(results)),
                    "url": url,
                    "domain": urlparse(url).netloc if url else "",
                    "snippet": self._summarize_text(content, 280),
                    "content": content,
                    "score": float(chunk.get("score", 0.0) or 0.0),
                    "metadata": chunk.get("metadata", {}) or {},
                }
            )

        return results

    def _build_summary(
        self,
        *,
        query: str,
        mode: str,
        sources: Sequence[Dict[str, Any]],
        results: Sequence[Dict[str, Any]],
        execution_time_ms: int,
        degraded: bool,
        warnings: Sequence[str],
    ) -> str:
        if not sources:
            if degraded and warnings:
                return (
                    f"Live search for '{query}' completed in degraded mode. "
                    f"No source cards were produced. Reason: {warnings[0]}"
                )
            return f"No live sources were found for '{query}'."

        top_domains = ", ".join(
            list(
                dict.fromkeys(
                    [
                        source.get("domain") or source.get("title", "")
                        for source in list(sources)[:3]
                        if source.get("domain") or source.get("title")
                    ]
                )
            )[:3]
        )

        base = (
            f"Live crawl for '{query}' completed in {execution_time_ms}ms using {mode} mode. "
            f"Collected {len(sources)} sources and ranked {len(results)} candidate passages."
        )

        if top_domains:
            base += f" Top domains: {top_domains}."

        if degraded and warnings:
            base += f" Degraded warning: {warnings[0]}"

        return base

    def _build_insights(
        self,
        *,
        mode: str,
        sources: Sequence[Dict[str, Any]],
        results: Sequence[Dict[str, Any]],
        urls_found: int,
        pages_crawled: int,
        degraded: bool,
    ) -> List[str]:
        insights = [
            f"Mode classified as {mode}.",
            f"Discovered {urls_found} candidate URLs and crawled {pages_crawled} pages.",
            f"Prepared {len(results)} ranked result cards from live crawl output.",
        ]

        if sources:
            primary = sources[0].get("domain") or sources[0].get("title") or "unknown"
            insights.append(f"Primary source domain: {primary}.")

        if degraded:
            insights.append("Pipeline completed with degraded internet capability.")

        return insights

    def _build_diagnostics(
        self,
        *,
        mode: str,
        strategy: Mapping[str, Any],
        execution_time_ms: int,
        urls_found: int,
        pages_crawled: int,
        chunks_produced: int,
        source_count: int,
        degraded: bool = False,
        warnings: Optional[List[str]] = None,
        status: str = "ok",
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "mode": mode,
            "strategy": strategy.get("query_strategy")
            or strategy.get("strategy")
            or "default",
            "latencyMs": execution_time_ms,
            "sourceCount": source_count,
            "urlsFound": urls_found,
            "pagesCrawled": pages_crawled,
            "chunksProduced": chunks_produced,
            "degraded": degraded,
            "warnings": warnings or [],
        }

    def _is_url_allowed(
        self,
        url: str,
        strategy: Mapping[str, Any],
    ) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().removeprefix("www.")

        if parsed.scheme not in {"http", "https"}:
            return False

        blocked_domains = {
            value.lower().removeprefix("www.")
            for value in strategy.get("blocked_domains", []) or []
        }
        allowed_domains = {
            value.lower().removeprefix("www.")
            for value in strategy.get("allowed_domains", []) or []
        }

        if blocked_domains and any(domain == blocked or domain.endswith(f".{blocked}") for blocked in blocked_domains):
            return False

        if allowed_domains:
            return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)

        return True

    def _summarize_text(self, text: str, limit: int) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 1)].rstrip() + "…"

    def _chunk_title(self, content: str, url: str, idx: int) -> str:
        for line in (content or "").splitlines():
            normalized = line.strip().lstrip("#").strip()
            if normalized:
                return normalized[:100]
        return urlparse(url).netloc or f"Result {idx + 1}"

    def _normalize_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None

        normalized = str(url).strip()
        if not normalized:
            return None

        if normalized.startswith("//"):
            normalized = f"https:{normalized}"

        parsed = urlparse(normalized)

        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if target:
                return unquote(target)

        if parsed.scheme not in {"http", "https"}:
            return None

        return normalized

    def _provider_name(self) -> str:
        return "crawl4ai"


def _normalize_domain_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None

    if isinstance(value, str):
        raw_values = [item.strip() for item in value.split(",")]
    elif isinstance(value, Iterable):
        raw_values = [str(item).strip() for item in value]
    else:
        return None

    normalized = [
        item.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
        for item in raw_values
        if item
    ]

    return list(dict.fromkeys(normalized)) or None
