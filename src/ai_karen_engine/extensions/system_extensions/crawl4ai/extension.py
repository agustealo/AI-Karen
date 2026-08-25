"""
Crawl4AI System Extension

First-party, system-installed, local-first, network-capable, browser-backed, READ-oriented extension.

Capabilities:
  - web.fetch: Simple URL fetching
  - web.crawl: Multi-page crawling with depth control
  - web.extract: Structured content extraction

Uses Crawl4AI 0.9.x native configuration where possible.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.contracts import (
    DataClassification,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionResult,
    ExtensionManifest,
    ResultTrust,
    SideEffectLevel,
    ResponseSource,
    TrustTier,
)

logger = logging.getLogger("kari.extensions.crawl4ai")


class Crawl4AIExtension:
    """Crawl4AI system extension implementation."""

    MANIFEST = ExtensionManifest(
        id="crawl4ai",
        name="Crawl4AI",
        version="0.9.0",
        plugin_api_version="1.0",
        description="First-party web crawling and content extraction system extension",
        entrypoint="Crawl4AIExtension",
        capabilities=[
            ExtensionCapability(
                id="web.fetch",
                version="1.0.0",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds",
                            "default": 30000
                        },
                        "user_agent": {
                            "type": "string",
                            "description": "Custom user agent string"
                        }
                    }
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "status_code": {"type": "integer"},
                        "content": {"type": "string"},
                        "content_type": {"type": "string"},
                        "headers": {"type": "object"}
                    }
                },
                required_permissions=["network.egress"],
                optional_permissions=["network.proxy"],
                required_roles=[],
                side_effect_level=SideEffectLevel.READ,
                risk_class="low",
                idempotency="idempotent",
                retry_policy={"max_retries": 3, "retryable": True},
                requires_network=True,
                requires_filesystem=False,
                requires_credentials=False,
                resource_profile={
                    "timeout_ms": 30000,
                    "max_retries": 3,
                },
                supports_streaming=False,
                supports_cancellation=True,
                data_classification=DataClassification.PUBLIC,
                result_trust=ResultTrust.UNTRUSTED_EXTERNAL,
            ),
            ExtensionCapability(
                id="web.crawl",
                version="1.0.0",
                input_schema={
                    "type": "object",
                    "required": ["url", "max_pages"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Starting URL for crawl"
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Maximum pages to crawl",
                            "minimum": 1
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum crawl depth",
                            "default": 3,
                            "minimum": 1
                        },
                        "follow_links": {
                            "type": "boolean",
                            "default": True
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "default": 30000
                        }
                    }
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "pages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "status_code": {"type": "integer"},
                                    "content": {"type": "string"},
                                    "depth": {"type": "integer"}
                                }
                            }
                        },
                        "total_pages": {"type": "integer"},
                        "crawl_time_ms": {"type": "number"}
                    }
                },
                required_permissions=["network.egress"],
                optional_permissions=["network.proxy"],
                required_roles=[],
                side_effect_level=SideEffectLevel.READ,
                risk_class="low",
                idempotency="idempotent",
                retry_policy={"max_retries": 2, "retryable": True},
                requires_network=True,
                requires_filesystem=False,
                requires_credentials=False,
                resource_profile={
                    "timeout_ms": 60000,
                    "max_retries": 2,
                },
                supports_streaming=True,
                supports_cancellation=True,
                data_classification=DataClassification.PUBLIC,
                result_trust=ResultTrust.UNTRUSTED_EXTERNAL,
            ),
            ExtensionCapability(
                id="web.extract",
                version="1.0.0",
                input_schema={
                    "type": "object",
                    "required": ["url", "extraction_type"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to extract from"
                        },
                        "extraction_type": {
                            "type": "string",
                            "enum": ["text", "markdown", "html", "json-ld", "article"],
                            "description": "Type of extraction to perform"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "default": 30000
                        }
                    }
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "extraction_type": {"type": "string"},
                        "extracted_content": {"type": "string"},
                        "metadata": {"type": "object"}
                    }
                },
                required_permissions=["network.egress"],
                optional_permissions=["network.proxy"],
                required_roles=[],
                side_effect_level=SideEffectLevel.READ,
                risk_class="low",
                idempotency="idempotent",
                retry_policy={"max_retries": 3, "retryable": True},
                requires_network=True,
                requires_filesystem=False,
                requires_credentials=False,
                resource_profile={
                    "timeout_ms": 30000,
                    "max_retries": 3,
                },
                supports_streaming=False,
                supports_cancellation=True,
                data_classification=DataClassification.PUBLIC,
                result_trust=ResultTrust.UNTRUSTED_EXTERNAL,
            ),
        ],
        required_permissions=[],
        optional_permissions=[],
        required_roles=[],
        requires_network=True,
        requires_filesystem=False,
        requires_credentials=False,
        requires_external_api=False,
        side_effect_level=SideEffectLevel.READ,
        timeout_ms=60000,
        max_retries=2,
        enabled_by_default=False,
        trusted_ui=False,
        trust_tier=TrustTier.FIRST_PARTY,
        isolation_mode="in_process",
        dependencies=[],
        metadata={
            "backend": "crawl4ai",
            "backend_version": "0.9.0",
            "category": "web",
            "author": "Karen System",
            "license": "proprietary",
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._crawler = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Crawl4AI extension."""
        if self._initialized:
            return

        try:
            import crawl4ai
            self._crawler = crawl4ai.AsyncWebCrawler()
            await self._crawler.start()
            self._initialized = True
            logger.info("Crawl4AI extension initialized successfully")
        except ImportError:
            logger.warning("Crawl4AI not installed. Extension will fail at execution time.")
        except Exception as e:
            logger.error("Failed to initialize Crawl4AI: %s", e)

    async def shutdown(self) -> None:
        """Shutdown Crawl4AI extension."""
        if self._crawler:
            await self._crawler.close()
            self._initialized = False
            logger.info("Crawl4AI extension shutdown complete")

    async def execute(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> ExtensionExecutionResult:
        """Execute a Crawl4AI capability."""

        capability = payload.get("_capability_id", "unknown")

        if not self._initialized:
            await self.initialize()

        if not self._crawler:
            return self._create_error_result(
                context,
                capability,
                "crawler_not_available",
                "Crawl4AI crawler not available or not initialized"
            )

        handlers = {
            "web.fetch": self._handle_web_fetch,
            "web.crawl": self._handle_web_crawl,
            "web.extract": self._handle_web_extract,
        }

        handler = handlers.get(capability)
        if handler is None:
            return self._create_error_result(
                context,
                capability,
                "unknown_capability",
                f"Unknown capability: {capability}"
            )

        try:
            start = time.perf_counter()
            result = await handler(payload, context)
            latency_ms = (time.perf_counter() - start) * 1000.0

            return self._create_success_result(
                context,
                capability,
                result,
                latency_ms,
                payload,
            )
        except Exception as e:
            logger.error("Crawl4AI execution error: %s", e)
            return self._create_error_result(
                context,
                capability,
                "execution_error",
                str(e)
            )

    async def _handle_web_fetch(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Dict[str, Any]:
        """Handle web.fetch capability."""
        url = payload.get("url")
        timeout_ms = payload.get("timeout_ms", 30000)
        user_agent = payload.get("user_agent")

        result = await self._crawler.arun(
            url=url,
            word_count_threshold=10,
            bypass_cache=True,
            timeout=timeout_ms / 1000.0,
        )

        content_hash = hashlib.sha256(result.markdown.encode()).hexdigest() if result.markdown else None

        return {
            "url": url,
            "final_url": result.url if hasattr(result, 'url') else url,
            "status_code": result.status_code if hasattr(result, 'status_code') else 200,
            "content": result.markdown or result.html,
            "content_type": result.metadata.get('content-type', 'text/html') if result.metadata else 'text/html',
            "headers": result.metadata or {},
            "content_hash": content_hash,
            "fetched_at": datetime.utcnow().isoformat(),
        }

    async def _handle_web_crawl(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Dict[str, Any]:
        """Handle web.crawl capability using Crawl4AI's adaptive crawling."""
        url = payload.get("url")
        max_pages = payload.get("max_pages", 10)
        max_depth = payload.get("max_depth", 3)
        follow_links = payload.get("follow_links", True)
        timeout_ms = payload.get("timeout_ms", 60000)

        try:
            from crawl4ai import CrawlerRunConfig
            config = CrawlerRunConfig(
                deep_crawl=True,
                bypass_cache=True,
                max_depth=max_depth,
            )
        except ImportError:
            config = None

        pages = []
        visited_urls = set()
        queue = [(url, 0)]

        start = time.perf_counter()

        while queue and len(pages) < max_pages:
            current_url, depth = queue.pop(0)

            if current_url in visited_urls or depth > max_depth:
                continue

            try:
                result = await self._crawler.arun(
                    url=current_url,
                    config=config,
                    timeout=timeout_ms / 1000.0,
                )

                pages.append({
                    "url": current_url,
                    "final_url": result.url if hasattr(result, 'url') else current_url,
                    "status_code": result.status_code if hasattr(result, 'status_code') else 200,
                    "content": result.markdown or result.html,
                    "depth": depth,
                    "fetched_at": datetime.utcnow().isoformat(),
                })

                visited_urls.add(current_url)

                if follow_links and result.links and depth < max_depth:
                    for link in result.links:
                        if link not in visited_urls and len(queue) + len(pages) < max_pages:
                            queue.append((link, depth + 1))

            except Exception as e:
                logger.warning("Failed to crawl %s: %s", current_url, e)

        crawl_time_ms = (time.perf_counter() - start) * 1000.0

        return {
            "pages": pages,
            "total_pages": len(pages),
            "crawl_time_ms": crawl_time_ms,
            "starting_url": url,
            "max_depth": max_depth,
        }

    async def _handle_web_extract(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Dict[str, Any]:
        """Handle web.extract capability."""
        url = payload.get("url")
        extraction_type = payload.get("extraction_type", "text")
        timeout_ms = payload.get("timeout_ms", 30000)

        result = await self._crawler.arun(
            url=url,
            bypass_cache=True,
            timeout=timeout_ms / 1000.0,
        )

        extracted_content = ""

        if extraction_type == "text":
            extracted_content = result.markdown or ""
        elif extraction_type == "html":
            extracted_content = result.html or ""
        elif extraction_type == "json-ld":
            extracted_content = result.metadata.get('json-ld', []) if result.metadata else []
        elif extraction_type == "article":
            extracted_content = result.cleaned_html or result.markdown or ""
        else:
            extracted_content = result.markdown or ""

        return {
            "url": url,
            "final_url": result.url if hasattr(result, 'url') else url,
            "extraction_type": extraction_type,
            "extracted_content": extracted_content,
            "metadata": {
                "title": result.metadata.get('title', '') if result.metadata else '',
                "description": result.metadata.get('description', '') if result.metadata else '',
                "language": result.metadata.get('language', '') if result.metadata else '',
            },
        }

    def _create_success_result(
        self,
        context: ExtensionExecutionContext,
        capability: str,
        payload: Dict[str, Any],
        latency_ms: float,
        original_payload: Dict[str, Any],
    ) -> ExtensionExecutionResult:
        """Create a successful execution result."""

        result = ExtensionExecutionResult(
            request_id=context.request_id,
            plugin_id=self.MANIFEST.id,
            plugin_version=self.MANIFEST.version,
            capability=capability,
            source=ResponseSource.PLUGIN,
            payload=payload,
            latency_ms=latency_ms,
            status="success",
            side_effects=["network"],
            permission_set=["network.egress"],
            correlation_id=context.correlation_id,
            policy_decision_id=context.policy_decision_id,
            trust_tier=TrustTier.FIRST_PARTY,
            result_trust=ResultTrust.UNTRUSTED_EXTERNAL,
            data_classification=DataClassification.PUBLIC,
            backend=self.MANIFEST.metadata.get("backend"),
            backend_version=self.MANIFEST.metadata.get("backend_version"),
            requested_url=original_payload.get("url"),
            final_url=payload.get("final_url", original_payload.get("url")),
            fetched_at=payload.get("fetched_at"),
            status_code=payload.get("status_code"),
            content_type=payload.get("content_type"),
            content_hash=payload.get("content_hash"),
            extraction_method="crawl4ai",
        )

        if capability == "web.crawl":
            result.crawl_depth = original_payload.get("max_depth")
            result.title = f"Crawled {len(payload.get('pages', []))} pages"

        return result

    def _create_error_result(
        self,
        context: ExtensionExecutionContext,
        capability: str,
        error_code: str,
        error_detail: str,
    ) -> ExtensionExecutionResult:
        """Create an error execution result."""

        return ExtensionExecutionResult(
            request_id=context.request_id,
            plugin_id=self.MANIFEST.id,
            plugin_version=self.MANIFEST.version,
            capability=capability,
            source=ResponseSource.UNAVAILABLE,
            payload=None,
            latency_ms=0.0,
            status="failed",
            error_code=error_code,
            error_detail=error_detail,
            side_effects=[],
            permission_set=[],
            correlation_id=context.correlation_id,
            policy_decision_id=context.policy_decision_id,
            trust_tier=TrustTier.FIRST_PARTY,
            result_trust=ResultTrust.UNVERIFIED,
            data_classification=DataClassification.PUBLIC,
        )


__all__ = ["Crawl4AIExtension"]