"""
Crawl4AI Integration.

Karen-grade acquisition layer for live web content retrieval.

Responsibilities:
- Validate and normalize crawl requests.
- Block unsafe/local/private/internal URLs before crawling.
- Fetch single or multiple URLs through Crawl4AI.
- Normalize Crawl4AI result objects into a stable internal schema.
- Return structured failures instead of fake placeholder content.
- Expose health and Prometheus metrics for diagnostics.
- Keep crawling separate from ranking, summarization, intent routing,
  memory writes, and response generation.

This integration should be used by internet/search services and plugins,
not by the UI directly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from prometheus_client import Counter, Histogram

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    _IMPORT_ERROR = None
except ImportError as e:
    AsyncWebCrawler = None  # type: ignore[assignment]
    BrowserConfig = None  # type: ignore[assignment]
    CacheMode = None  # type: ignore[assignment]
    CrawlerRunConfig = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(e)


logger = logging.getLogger(__name__)


CRAWL4AI_REQUESTS = Counter(
    "karen_crawl4ai_requests_total",
    "Total Crawl4AI acquisition requests.",
    ["status", "failure_code"],
)

CRAWL4AI_BATCHES = Counter(
    "karen_crawl4ai_batches_total",
    "Total Crawl4AI batch requests.",
    ["status"],
)

CRAWL4AI_LATENCY = Histogram(
    "karen_crawl4ai_latency_seconds",
    "Crawl4AI single URL acquisition latency in seconds.",
    ["status", "failure_code"],
)

CRAWL4AI_BATCH_SIZE = Histogram(
    "karen_crawl4ai_batch_size",
    "Number of URLs requested per Crawl4AI batch.",
)


class CrawlFailureCode(str, Enum):
    """Stable failure codes for caller-side routing and observability."""

    DEPENDENCY_MISSING = "dependency_missing"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    BLOCKED_HOST = "blocked_host"
    PRIVATE_NETWORK_BLOCKED = "private_network_blocked"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    TIMEOUT = "timeout"
    CRAWLER_ERROR = "crawler_error"
    EMPTY_RESULT = "empty_result"
    PARTIAL_BATCH_FAILURE = "partial_batch_failure"


@dataclass(frozen=True)
class Crawl4AISettings:
    """
    Runtime settings for Crawl4AI integration.

    This should be hydrated from Karen's centralized app settings layer.
    """

    headless: bool = True
    verbose: bool = False
    timeout_seconds: float = 45.0
    max_concurrency: int = 5
    user_agent: Optional[str] = None
    bypass_cache: bool = False
    include_raw_html: bool = False
    include_cleaned_html: bool = False
    include_screenshot: bool = False
    include_pdf: bool = False
    resolve_dns_for_safety: bool = True
    allow_private_networks: bool = False
    allowed_schemes: Sequence[str] = field(default_factory=lambda: ("http", "https"))
    blocked_hosts: Sequence[str] = field(
        default_factory=lambda: (
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
            "metadata.google.internal",
            "169.254.169.254",
        )
    )


@dataclass(frozen=True)
class CrawlRequest:
    """Normalized request contract for a single crawl."""

    url: str
    bypass_cache: Optional[bool] = None
    timeout_seconds: Optional[float] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrawlResult:
    """Stable response contract returned by this integration."""

    url: str
    final_url: str
    markdown: str
    text: str
    html: str
    cleaned_html: str
    links: List[Dict[str, Any]]
    media: Dict[str, Any]
    metadata: Dict[str, Any]
    extracted_content: Optional[Any]
    success: bool
    status_code: Optional[int]
    error: Optional[str]
    failure_code: Optional[str]
    elapsed_ms: float
    source: str = "crawl4ai"

    def to_dict(self) -> Dict[str, Any]:
        """Return JSON-serializable result payload."""
        return asdict(self)


class Crawl4AIIntegration:
    """
    Production-grade Crawl4AI integration layer.

    This class performs content acquisition and result normalization only.

    It must not:
    - Rank search results.
    - Summarize content.
    - Choose prompts.
    - Execute plugin logic.
    - Write memory directly.
    - Decide final assistant response wording.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_seconds: float = 45.0,
        max_concurrency: int = 5,
        user_agent: Optional[str] = None,
        verbose: bool = False,
        include_raw_html: bool = False,
        include_cleaned_html: bool = False,
        include_screenshot: bool = False,
        include_pdf: bool = False,
        bypass_cache: bool = False,
        blocked_hosts: Optional[Sequence[str]] = None,
        allowed_schemes: Optional[Sequence[str]] = None,
        resolve_dns_for_safety: bool = True,
        allow_private_networks: bool = False,
    ) -> None:
        default_settings = Crawl4AISettings()

        self.settings = Crawl4AISettings(
            headless=bool(headless),
            verbose=bool(verbose),
            timeout_seconds=max(float(timeout_seconds), 1.0),
            max_concurrency=max(int(max_concurrency), 1),
            user_agent=user_agent,
            bypass_cache=bool(bypass_cache),
            include_raw_html=bool(include_raw_html),
            include_cleaned_html=bool(include_cleaned_html),
            include_screenshot=bool(include_screenshot),
            include_pdf=bool(include_pdf),
            resolve_dns_for_safety=bool(resolve_dns_for_safety),
            allow_private_networks=bool(allow_private_networks),
            blocked_hosts=tuple(blocked_hosts)
            if blocked_hosts is not None
            else default_settings.blocked_hosts,
            allowed_schemes=tuple(allowed_schemes)
            if allowed_schemes is not None
            else default_settings.allowed_schemes,
        )

        self.available = (
            AsyncWebCrawler is not None
            and BrowserConfig is not None
            and CrawlerRunConfig is not None
        )

        if not self.available:
            error_details = f": {_IMPORT_ERROR}" if _IMPORT_ERROR else ""
            logger.info(
                f"Crawl4AI is not installed or could not be imported{error_details}. "
                "Crawl4AIIntegration will return structured dependency failures. "
                "To fix this, ensure 'crawl4ai' and 'playwright' are in requirements.txt "
                "and run 'playwright install chromium && playwright install-deps chromium'."
            )

        self.browser_config = self._build_browser_config()

    @classmethod
    def from_settings(cls, settings: Crawl4AISettings) -> "Crawl4AIIntegration":
        """Create an integration instance from a settings object."""
        return cls(
            headless=settings.headless,
            timeout_seconds=settings.timeout_seconds,
            max_concurrency=settings.max_concurrency,
            user_agent=settings.user_agent,
            verbose=settings.verbose,
            include_raw_html=settings.include_raw_html,
            include_cleaned_html=settings.include_cleaned_html,
            include_screenshot=settings.include_screenshot,
            include_pdf=settings.include_pdf,
            bypass_cache=settings.bypass_cache,
            blocked_hosts=settings.blocked_hosts,
            allowed_schemes=settings.allowed_schemes,
            resolve_dns_for_safety=settings.resolve_dns_for_safety,
            allow_private_networks=settings.allow_private_networks,
        )

    def health(self) -> Dict[str, Any]:
        """Return integration health for diagnostics and admin UI."""
        return {
            "integration": "crawl4ai",
            "available": self.available,
            "dependency": "crawl4ai",
            "headless": self.settings.headless,
            "timeout_seconds": self.settings.timeout_seconds,
            "max_concurrency": self.settings.max_concurrency,
            "bypass_cache": self.settings.bypass_cache,
            "include_raw_html": self.settings.include_raw_html,
            "include_cleaned_html": self.settings.include_cleaned_html,
            "include_screenshot": self.settings.include_screenshot,
            "include_pdf": self.settings.include_pdf,
            "resolve_dns_for_safety": self.settings.resolve_dns_for_safety,
            "allow_private_networks": self.settings.allow_private_networks,
            "allowed_schemes": list(self.settings.allowed_schemes),
            "blocked_hosts": list(self.settings.blocked_hosts),
        }

    async def fetch_url(
        self,
        url: str,
        bypass_cache: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        extraction_strategy: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Fetch a single URL and return normalized content.

        Returns a stable dictionary contract. No placeholder/mock content is emitted.
        """
        request = CrawlRequest(
            url=url,
            bypass_cache=bypass_cache,
            timeout_seconds=timeout_seconds,
            metadata={
                **(metadata or {}),
                "_extraction_strategy": extraction_strategy,
            },
        )
        result = await self.fetch(request)
        return result.to_dict()

    async def fetch(self, request: CrawlRequest) -> CrawlResult:
        """Fetch a single CrawlRequest and return a CrawlResult."""
        results = await self.fetch_requests([request])
        if not results:
            return self._failure_result(
                url=request.url,
                started=time.perf_counter(),
                error="Crawl request produced no result.",
                failure_code=CrawlFailureCode.EMPTY_RESULT.value,
                metadata={"request_metadata": dict(request.metadata)},
            )
        return results[0]

    async def fetch_many(
        self,
        urls: Sequence[str],
        bypass_cache: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch multiple URLs concurrently with bounded concurrency.

        The result order matches the input order.
        """
        requests = [
            CrawlRequest(
                url=url,
                bypass_cache=bypass_cache,
                timeout_seconds=timeout_seconds,
                metadata={"batch_index": index},
            )
            for index, url in enumerate(urls)
        ]

        results = await self.fetch_requests(requests)
        return [result.to_dict() for result in results]

    async def fetch_requests(self, requests: Sequence[CrawlRequest]) -> List[CrawlResult]:
        """
        Fetch multiple CrawlRequest objects with bounded concurrency.

        Uses a single crawler instance for the whole batch to save memory and
        avoid redundant browser context creation.
        """
        if not requests:
            return []

        batch_started = time.perf_counter()
        CRAWL4AI_BATCH_SIZE.observe(len(requests))

        if not self.available:
            dependency_results: List[CrawlResult] = [
                self._failure_result(
                    url=req.url,
                    started=time.perf_counter(),
                    error="Crawl4AI is not installed.",
                    failure_code=CrawlFailureCode.DEPENDENCY_MISSING.value,
                    metadata={"request_metadata": dict(req.metadata)},
                )
                for req in requests
            ]
            CRAWL4AI_BATCHES.labels(status="dependency_missing").inc()
            return dependency_results

        pending_results: List[Optional[CrawlResult]] = [None] * len(requests)

        crawler_factory = AsyncWebCrawler
        assert crawler_factory is not None

        try:
            async with crawler_factory(config=self.browser_config) as crawler:
                semaphore = asyncio.Semaphore(self.settings.max_concurrency)

                async def crawl_one(index: int, req: CrawlRequest) -> None:
                    async with semaphore:
                        pending_results[index] = await self._fetch_with_crawler(
                            crawler, req
                        )

                tasks = [
                    crawl_one(index, request)
                    for index, request in enumerate(requests)
                ]
                await asyncio.gather(*tasks)

        except Exception as exc:
            logger.exception("Crawl4AI batch failed before all requests could run.")
            CRAWL4AI_BATCHES.labels(status="batch_error").inc()

            return [
                item
                if item is not None
                else self._failure_result(
                    url=requests[index].url,
                    started=batch_started,
                    error=str(exc),
                    failure_code=CrawlFailureCode.PARTIAL_BATCH_FAILURE.value,
                    metadata={"request_metadata": dict(requests[index].metadata)},
                )
                for index, item in enumerate(pending_results)
            ]

        final_results: List[CrawlResult] = []
        for index, result in enumerate(pending_results):
            if result is not None:
                final_results.append(result)
            else:
                final_results.append(
                    self._failure_result(
                        url=requests[index].url,
                        started=batch_started,
                        error="Unknown batch processing error.",
                        failure_code=CrawlFailureCode.PARTIAL_BATCH_FAILURE.value,
                        metadata={"request_metadata": dict(requests[index].metadata)},
                    )
                )

        status = "ok" if all(result.success for result in final_results) else "partial"
        CRAWL4AI_BATCHES.labels(status=status).inc()

        return final_results

    async def close(self) -> None:
        """
        Reserved lifecycle hook.

        Crawl4AI crawler instances are currently scoped per call through async
        context managers. This hook exists so callers can treat integrations
        uniformly.
        """
        return None

    async def _fetch_with_crawler(self, crawler: Any, req: CrawlRequest) -> CrawlResult:
        """Fetch one request using an already-open Crawl4AI crawler."""
        started = time.perf_counter()
        normalized_url = self._normalize_url(req.url)
        validation_error = self._validate_url(normalized_url)

        if validation_error is not None:
            result = self._failure_result(
                url=normalized_url or req.url,
                started=started,
                error=validation_error["error"],
                failure_code=validation_error["failure_code"],
                metadata={
                    "request_metadata": dict(req.metadata),
                    "validation": validation_error,
                },
            )
            self._observe_result(result)
            return result

        try:
            timeout = max(float(req.timeout_seconds or self.settings.timeout_seconds), 1.0)
            bypass_cache = bool(
                self.settings.bypass_cache
                if req.bypass_cache is None
                else req.bypass_cache
            )
            
            # Extract strategy from internal metadata key
            extraction_strategy = req.metadata.get("_extraction_strategy")
            run_config = self._build_run_config(
                bypass_cache=bypass_cache,
                extraction_strategy=extraction_strategy,
            )

            logger.info(f"🚀 Crawl4AI starting arun for {normalized_url} (timeout={timeout}s, strategy={type(extraction_strategy).__name__ if extraction_strategy else 'None'})")
            raw_result = await asyncio.wait_for(
                crawler.arun(url=normalized_url, config=run_config),
                timeout=timeout,
            )
            logger.info(f"✅ Crawl4AI arun completed for {normalized_url}")

            if raw_result is None:
                result = self._failure_result(
                    url=normalized_url,
                    started=started,
                    error="Crawl4AI returned an empty result.",
                    failure_code=CrawlFailureCode.EMPTY_RESULT.value,
                    metadata={"request_metadata": dict(req.metadata)},
                )
                self._observe_result(result)
                return result

            result = self._normalize_result(
                result=raw_result,
                requested_url=normalized_url,
                started=started,
                request_metadata=dict(req.metadata),
            )
            self._observe_result(result)
            return result

        except asyncio.TimeoutError:
            result = self._failure_result(
                url=normalized_url,
                started=started,
                error=f"Crawl timed out after {timeout} seconds.",
                failure_code=CrawlFailureCode.TIMEOUT.value,
                metadata={"request_metadata": dict(req.metadata)},
            )
            self._observe_result(result)
            return result

        except Exception as exc:
            logger.exception("Crawl4AI failed for URL '%s'.", normalized_url)
            result = self._failure_result(
                url=normalized_url,
                started=started,
                error=str(exc),
                failure_code=CrawlFailureCode.CRAWLER_ERROR.value,
                metadata={"request_metadata": dict(req.metadata)},
            )
            self._observe_result(result)
            return result

    def _build_extraction_strategy(self, config: Optional[Dict[str, Any]]) -> Optional[Any]:
        """Build a Crawl4AI extraction strategy from a configuration dictionary."""
        if not config or not self.available:
            return None

        try:
            strategy_type = config.get("type", "instruction")
            
            if strategy_type == "css":
                from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
                schema = config.get("schema")
                if not schema:
                    return None
                return JsonCssExtractionStrategy(schema, verbose=self.settings.verbose)
                
            elif strategy_type == "xpath":
                from crawl4ai.extraction_strategy import JsonXPathExtractionStrategy
                schema = config.get("schema")
                if not schema:
                    return None
                return JsonXPathExtractionStrategy(schema, verbose=self.settings.verbose)
                
            elif strategy_type in {"llm", "schema", "instruction"}:
                from crawl4ai.extraction_strategy import LLMExtractionStrategy
                
                # LLM strategy requires provider and other details
                # If they aren't provided, we use a default instruction-based one if possible
                instruction = config.get("instruction") or config.get("schema")
                if not instruction:
                    return None
                    
                return LLMExtractionStrategy(
                    provider=config.get("provider", "openai/gpt-4o-mini"),
                    api_token=config.get("api_token"),
                    instruction=str(instruction),
                    schema=config.get("schema") if strategy_type == "schema" else None,
                    verbose=self.settings.verbose
                )
        except Exception as e:
            logger.warning(f"Failed to build extraction strategy: {e}")
            
        return None

    def _build_browser_config(self) -> Any:
        """Build BrowserConfig while tolerating Crawl4AI version differences."""
        if BrowserConfig is None:
            return None

        kwargs: Dict[str, Any] = {
            "headless": self.settings.headless,
            "verbose": self.settings.verbose,
        }

        if self.settings.user_agent:
            kwargs["user_agent"] = self.settings.user_agent

        return self._safe_construct(
            BrowserConfig,
            kwargs=kwargs,
            fallback_kwargs={
                "headless": self.settings.headless,
            },
        )

    def _build_run_config(
        self,
        bypass_cache: bool,
        extraction_strategy: Optional[Any] = None,
    ) -> Any:
        """Build CrawlerRunConfig while tolerating Crawl4AI version differences."""
        if CrawlerRunConfig is None:
            return None

        cache_mode: Any = None
        if CacheMode is not None:
            cache_mode = CacheMode.BYPASS if bypass_cache else CacheMode.ENABLED

        kwargs: Dict[str, Any] = {}

        if cache_mode is not None:
            kwargs["cache_mode"] = cache_mode

        if extraction_strategy is not None:
            kwargs["extraction_strategy"] = extraction_strategy

        if not self.settings.include_raw_html:
            kwargs["word_count_threshold"] = 10

        if self.settings.include_screenshot:
            kwargs["screenshot"] = True

        if self.settings.include_pdf:
            kwargs["pdf"] = True

        return self._safe_construct(
            CrawlerRunConfig,
            kwargs=kwargs,
            fallback_kwargs={},
        )

    @staticmethod
    def _safe_construct(
        factory: Any,
        kwargs: Dict[str, Any],
        fallback_kwargs: Dict[str, Any],
    ) -> Any:
        """
        Construct Crawl4AI config objects while avoiding version-specific kwarg crashes.
        """
        try:
            return factory(**kwargs)
        except TypeError:
            logger.debug(
                "Falling back to reduced constructor kwargs for %s.",
                getattr(factory, "__name__", str(factory)),
                exc_info=True,
            )
            return factory(**fallback_kwargs)

    def _normalize_result(
        self,
        result: Any,
        requested_url: str,
        started: float,
        request_metadata: Optional[Mapping[str, Any]] = None,
    ) -> CrawlResult:
        """Normalize Crawl4AI result into Karen's stable schema."""
        markdown = self._extract_markdown(result)
        text = self._extract_text(result, markdown)
        html = self._extract_html(result) if self.settings.include_raw_html else ""
        cleaned_html = (
            self._extract_cleaned_html(result)
            if self.settings.include_cleaned_html
            else ""
        )
        links = self._normalize_links(getattr(result, "links", []))
        media = self._normalize_media(getattr(result, "media", {}))
        metadata = self._normalize_metadata(getattr(result, "metadata", {}))
        extracted_content = getattr(result, "extracted_content", None)

        success = bool(getattr(result, "success", True))
        status_code = self._extract_status_code(result)
        error = self._extract_error(result)

        final_url = first_non_empty(
            getattr(result, "final_url", None),
            getattr(result, "redirected_url", None),
            getattr(result, "url", None),
            requested_url,
        )

        normalized_metadata: Dict[str, Any] = {
            "request_metadata": dict(request_metadata or {}),
            "crawl4ai_metadata": metadata,
            "content_lengths": {
                "markdown": len(markdown),
                "text": len(text),
                "html": len(html),
                "cleaned_html": len(cleaned_html),
            },
        }

        screenshot = getattr(result, "screenshot", None)
        pdf = getattr(result, "pdf", None)

        if screenshot is not None:
            normalized_metadata["screenshot_available"] = bool(screenshot)

        if pdf is not None:
            normalized_metadata["pdf_available"] = bool(pdf)

        failure_code: Optional[str] = None
        if not success:
            failure_code = CrawlFailureCode.CRAWLER_ERROR.value

        if success and not markdown and not text:
            success = False
            error = error or "Crawl succeeded but returned no usable text or markdown."
            failure_code = CrawlFailureCode.EMPTY_RESULT.value

        return CrawlResult(
            url=requested_url,
            final_url=final_url,
            markdown=markdown,
            text=text,
            html=html,
            cleaned_html=cleaned_html,
            links=links,
            media=media,
            metadata=normalized_metadata,
            extracted_content=extracted_content,
            success=success,
            status_code=status_code,
            error=error,
            failure_code=failure_code,
            elapsed_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _extract_markdown(result: Any) -> str:
        """
        Extract markdown across Crawl4AI versions.

        Supported observed shapes:
        - result.markdown as string
        - result.markdown.raw_markdown
        - result.markdown.fit_markdown
        - result.markdown.markdown
        - result.markdown.content
        - result.markdown_v2.raw_markdown
        """
        markdown_obj = getattr(result, "markdown", None)

        if isinstance(markdown_obj, str):
            return markdown_obj.strip()

        if markdown_obj is not None:
            for attr in ("raw_markdown", "fit_markdown", "markdown", "content"):
                value = getattr(markdown_obj, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        markdown_v2 = getattr(result, "markdown_v2", None)
        if markdown_v2 is not None:
            for attr in ("raw_markdown", "fit_markdown", "markdown", "content"):
                value = getattr(markdown_v2, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        for attr in ("raw_markdown", "fit_markdown", "markdown_content"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    @staticmethod
    def _extract_text(result: Any, markdown: str) -> str:
        """Extract text fallback from Crawl4AI result."""
        for attr in ("text", "cleaned_text", "extracted_text"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return markdown.strip()

    @staticmethod
    def _extract_html(result: Any) -> str:
        """Extract raw HTML if available."""
        for attr in ("html", "raw_html"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value

        return ""

    @staticmethod
    def _extract_cleaned_html(result: Any) -> str:
        """Extract cleaned HTML if available."""
        for attr in ("cleaned_html", "fit_html"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value

        return ""

    @staticmethod
    def _extract_status_code(result: Any) -> Optional[int]:
        """Extract status code safely."""
        for attr in ("status_code", "response_status", "http_status"):
            value = getattr(result, attr, None)
            if isinstance(value, int):
                return value

            if isinstance(value, str) and value.isdigit():
                return int(value)

        return None

    @staticmethod
    def _extract_error(result: Any) -> Optional[str]:
        """Extract error message safely."""
        for attr in ("error", "error_message", "exception"):
            value = getattr(result, attr, None)
            if value:
                return str(value)

        return None

    @staticmethod
    def _normalize_links(raw_links: Any) -> List[Dict[str, Any]]:
        """Normalize Crawl4AI links into a list of dictionaries."""
        if not raw_links:
            return []

        normalized: List[Dict[str, Any]] = []

        if isinstance(raw_links, Mapping):
            for category, links in raw_links.items():
                if isinstance(links, Iterable) and not isinstance(
                    links,
                    (str, bytes, Mapping),
                ):
                    for link in links:
                        normalized.append(
                            Crawl4AIIntegration._normalize_single_link(
                                link,
                                category=str(category),
                            )
                        )
                else:
                    normalized.append(
                        {
                            "url": str(links),
                            "text": "",
                            "category": str(category),
                            "metadata": {},
                        }
                    )

            return normalized

        if isinstance(raw_links, Iterable) and not isinstance(raw_links, (str, bytes)):
            for link in raw_links:
                normalized.append(Crawl4AIIntegration._normalize_single_link(link))

        return normalized

    @staticmethod
    def _normalize_single_link(
        link: Any,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Normalize one link item."""
        if isinstance(link, Mapping):
            href = first_non_empty(
                link.get("href"),
                link.get("url"),
                link.get("link"),
            )
            text = first_non_empty(
                link.get("text"),
                link.get("title"),
                link.get("label"),
            )
            return {
                "url": href,
                "text": text,
                "category": category or str(link.get("category") or ""),
                "metadata": {
                    key: value
                    for key, value in dict(link).items()
                    if key
                    not in {
                        "href",
                        "url",
                        "link",
                        "text",
                        "title",
                        "label",
                        "category",
                    }
                },
            }

        return {
            "url": str(link),
            "text": "",
            "category": category or "",
            "metadata": {},
        }

    @staticmethod
    def _normalize_media(raw_media: Any) -> Dict[str, Any]:
        """Normalize Crawl4AI media payload."""
        if not raw_media:
            return {}

        if isinstance(raw_media, Mapping):
            return dict(raw_media)

        if isinstance(raw_media, Iterable) and not isinstance(raw_media, (str, bytes)):
            return {"items": list(raw_media)}

        return {"items": raw_media}

    @staticmethod
    def _normalize_metadata(raw_metadata: Any) -> Dict[str, Any]:
        """Normalize metadata payload."""
        if not raw_metadata:
            return {}

        if isinstance(raw_metadata, Mapping):
            return dict(raw_metadata)

        return {"value": str(raw_metadata)}

    def _validate_url(self, url: str) -> Optional[Dict[str, str]]:
        """Validate URL before crawl."""
        if not url:
            return {
                "error": "URL is required.",
                "failure_code": CrawlFailureCode.INVALID_URL.value,
            }

        parsed = urlparse(url)

        if parsed.scheme.lower() not in {
            scheme.lower() for scheme in self.settings.allowed_schemes
        }:
            return {
                "error": (
                    f"Unsupported URL scheme '{parsed.scheme}'. "
                    f"Allowed schemes: {', '.join(self.settings.allowed_schemes)}."
                ),
                "failure_code": CrawlFailureCode.UNSUPPORTED_SCHEME.value,
            }

        if not parsed.netloc:
            return {
                "error": "URL must include a valid hostname.",
                "failure_code": CrawlFailureCode.INVALID_URL.value,
            }

        hostname = (parsed.hostname or "").lower().strip("[]")

        if not hostname:
            return {
                "error": "URL must include a valid hostname.",
                "failure_code": CrawlFailureCode.INVALID_URL.value,
            }

        if hostname in {host.lower() for host in self.settings.blocked_hosts}:
            return {
                "error": f"Blocked hostname '{hostname}'.",
                "failure_code": CrawlFailureCode.BLOCKED_HOST.value,
            }

        if self._is_ip_private_or_reserved(hostname):
            if not self.settings.allow_private_networks:
                return {
                    "error": f"Private, local, or reserved IP address blocked: '{hostname}'.",
                    "failure_code": CrawlFailureCode.PRIVATE_NETWORK_BLOCKED.value,
                }

        if self.settings.resolve_dns_for_safety and not self.settings.allow_private_networks:
            dns_error = self._validate_dns_safety(hostname)
            if dns_error is not None:
                return dns_error

        return None

    def _validate_dns_safety(self, hostname: str) -> Optional[Dict[str, str]]:
        """
        Resolve hostname and block private/local/reserved IP targets.

        This reduces SSRF risk when a public-looking hostname resolves to a
        private/internal address.
        """
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return {
                "error": f"DNS resolution failed for hostname '{hostname}'.",
                "failure_code": CrawlFailureCode.DNS_RESOLUTION_FAILED.value,
            }

        resolved_ips = set()
        for info in addr_infos:
            if not info or len(info) < 5:
                continue

            sockaddr = info[4]
            if not sockaddr:
                continue

            ip_value = sockaddr[0]
            if ip_value:
                resolved_ips.add(str(ip_value))

        for ip_value in resolved_ips:
            if self._is_ip_private_or_reserved(ip_value):
                return {
                    "error": (
                        f"Hostname '{hostname}' resolves to blocked private, "
                        f"local, or reserved address '{ip_value}'."
                    ),
                    "failure_code": CrawlFailureCode.PRIVATE_NETWORK_BLOCKED.value,
                }

        return None

    @staticmethod
    def _is_ip_private_or_reserved(value: str) -> bool:
        """Return True when value is an IP that should not be crawled by default."""
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return False

        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize user-provided URL."""
        cleaned = str(url or "").strip()

        if not cleaned:
            return ""

        parsed = urlparse(cleaned)

        if not parsed.scheme and "." in cleaned:
            return f"https://{cleaned}"

        return cleaned

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        """Return elapsed milliseconds."""
        return round((time.perf_counter() - started) * 1000, 3)

    def _failure_result(
        self,
        url: str,
        started: float,
        error: str,
        failure_code: str,
        metadata: Optional[Mapping[str, Any]] = None,
        status_code: Optional[int] = None,
    ) -> CrawlResult:
        """Create a structured failure result."""
        return CrawlResult(
            url=url,
            final_url=url,
            markdown="",
            text="",
            html="",
            cleaned_html="",
            links=[],
            media={},
            metadata=dict(metadata or {}),
            success=False,
            status_code=status_code,
            error=error,
            failure_code=failure_code,
            elapsed_ms=self._elapsed_ms(started),
        )

    def _observe_result(self, result: CrawlResult) -> None:
        """Record Prometheus metrics for a single crawl result."""
        status = "success" if result.success else "failure"
        failure_code = result.failure_code or "none"

        CRAWL4AI_REQUESTS.labels(
            status=status,
            failure_code=failure_code,
        ).inc()

        CRAWL4AI_LATENCY.labels(
            status=status,
            failure_code=failure_code,
        ).observe(result.elapsed_ms / 1000)


_integration_instance: Optional[Crawl4AIIntegration] = None


def get_crawl4ai_integration() -> Crawl4AIIntegration:
    """
    Get or create the singleton Crawl4AI integration instance.
    """
    global _integration_instance
    if _integration_instance is None:
        _integration_instance = Crawl4AIIntegration()
    return _integration_instance


async def close_crawl4ai_integration() -> None:
    """
    Close the global Crawl4AI integration instance.
    """
    global _integration_instance
    if _integration_instance:
        await _integration_instance.close()
        _integration_instance = None


def first_non_empty(*values: Any) -> str:
    """Return the first non-empty string value."""
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned

    return ""
