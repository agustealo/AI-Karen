"""
Web search client with support for multiple search providers.

This module now delegates provider selection to WebSearchProviderRegistry.
Provider configurations are sourced from central defaults and caller settings.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from ai_karen_engine.services.search.web_search_defaults import build_provider_configs
from ai_karen_engine.services.search.web_search_provider_registry import (
    WebSearchProviderDescriptor,
    WebSearchProviderRegistry,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Individual search result"""
    title: str
    url: str
    snippet: str
    content: Optional[str] = None
    published_date: Optional[str] = None
    source: Optional[str] = None


@dataclass
class SearchResponse:
    """Complete search response"""
    query: str
    results: List[SearchResult]
    total_results: Optional[int] = None
    search_time: Optional[float] = None
    provider: str = "unknown"
    error: Optional[str] = None


class WebSearchClient:
    """
    Multi-provider web search client.

    Provider selection and fallback order are delegated to
    WebSearchProviderRegistry instead of being hardcoded here.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        self.settings = settings or {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.registry = WebSearchProviderRegistry(settings=self.settings)

    async def __aenter__(self) -> "WebSearchClient":
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None

    async def search(
        self,
        query: str,
        max_results: int = 5,
        time_range: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Perform web search using the registry-selected provider.
        """
        if not query or not query.strip():
            return SearchResponse(
                query=query,
                results=[],
                provider="none",
                error="Empty query",
            )

        selected = self.registry.select_provider(
            requested=provider,
        )
        if not selected:
            return SearchResponse(
                query=query,
                results=[],
                provider="none",
                error="No enabled search providers are configured.",
            )

        try:
            return await self._search_with_provider(
                selected,
                query,
                max_results,
                time_range,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("Provider %s failed: %s", selected, exc, exc_info=True)
            return SearchResponse(
                query=query,
                results=[],
                provider=selected,
                error=str(exc),
            )

    async def _search_with_provider(
        self,
        provider_name: str,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        if provider_name == "duckduckgo":
            return await self._search_duckduckgo(query, max_results, **kwargs)
        if provider_name == "brave_search":
            return await self._search_brave_api(query, max_results, **kwargs)
        if provider_name == "brave_search_free":
            return await self._search_brave_free(query, max_results, **kwargs)
        if provider_name == "searxng":
            return await self._search_searxng(query, max_results, time_range, **kwargs)
        if provider_name == "tavily":
            return await self._search_tavily(query, max_results, time_range, **kwargs)
        if provider_name == "mojeek":
            return await self._search_mojeek(query, max_results, **kwargs)
        if provider_name == "wikipedia":
            return await self._search_wikipedia(query, max_results, **kwargs)
        if provider_name == "google_custom_search":
            return await self._search_google(query, max_results, time_range, **kwargs)
        if provider_name == "startpage":
            return await self._search_startpage(query, max_results, **kwargs)

        return SearchResponse(
            query=query,
            results=[],
            provider="none",
            error=f"Unknown provider: {provider_name}",
        )

    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        try:
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query, "kl": "us-en"}
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://duckduckgo.com/",
                "DNT": "1",
            }

            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status not in (200, 202):
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="duckduckgo",
                        error=f"HTTP {response.status}",
                    )

                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            results = []
            result_divs = soup.find_all("div", class_="result") or soup.find_all("div", class_="web-result")

            for div in result_divs[:max_results]:
                try:
                    title_elem = div.find("a", class_="result__a") or div.find("a", class_="result__url") or div.find("a")
                    snippet_elem = div.find("a", class_="result__snippet")
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    url = title_elem.get("href", "")
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    if title and url:
                        results.append(SearchResult(title=title, url=url, snippet=snippet, source="duckduckgo"))
                except Exception as exc:
                    logger.warning("Failed to parse DuckDuckGo result: %s", exc)
                    continue

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="duckduckgo",
            )
        except Exception as exc:
            logger.error("DuckDuckGo search error: %s", exc)
            return SearchResponse(query=query, results=[], provider="duckduckgo", error=str(exc))

    async def _search_searxng(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        config = self.registry.get_config("searxng")
        instances = config.get("instances") or []
        last_error = "All instances failed"

        for instance_url in instances[:3]:
            try:
                url = f"{instance_url.rstrip('/')}/search"
                params = {"q": query, "format": "json", "safesearch": 1, "categories": "general"}
                if time_range:
                    time_map = {"d": "day", "w": "week", "m": "month", "y": "year"}
                    params["time_range"] = time_map.get(time_range.lower(), time_range)

                async with self.session.get(url, params=params, timeout=10) as response:
                    if response.status != 200:
                        last_error = f"HTTP {response.status} from {instance_url}"
                        continue

                    data = await response.json()
                    results = []
                    for item in data.get("results", [])[:max_results]:
                        results.append(
                            SearchResult(
                                title=item.get("title", ""),
                                url=item.get("url", ""),
                                snippet=item.get("content") or "",
                                content=item.get("content"),
                                source=f"searxng ({instance_url})",
                            )
                        )

                    if results:
                        return SearchResponse(
                            query=query,
                            results=results,
                            total_results=len(results),
                            provider="searxng",
                        )

                    last_error = f"No results from {instance_url}"
            except Exception as exc:
                last_error = f"Error from {instance_url}: {exc}"
                logger.debug("SearxNG instance %s failed: %s", instance_url, exc)
                continue

        return SearchResponse(query=query, results=[], provider="searxng", error=last_error)

    async def _search_brave_api(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        config = self.registry.get_config("brave_search")
        api_key = self.settings.get("brave_api_key") or config.get("api_key")
        api_url = config.get("api_url", "https://api.search.brave.com/res/v1/web/search")

        try:
            params = {"q": query, "count": max_results}
            headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

            async with self.session.get(api_url, params=params, headers=headers) as response:
                if response.status != 200:
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="brave_search",
                        error=f"HTTP {response.status}",
                    )

                data = await response.json()
                results = []
                for item in data.get("web", {}).get("results", []):
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=item.get("description") or "",
                            content=item.get("description"),
                            source="brave_search",
                        )
                    )

                return SearchResponse(
                    query=query,
                    results=results,
                    total_results=len(results),
                    provider="brave_search",
                )
        except Exception as exc:
            logger.error("Brave API search error: %s", exc)
            return SearchResponse(query=query, results=[], provider="brave_search", error=str(exc))

    async def _search_brave_free(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        try:
            url = "https://search.brave.com/search"
            params = {"q": query}
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.8,*/*;q=0.8",
            }

            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="brave_search_free",
                        error=f"HTTP {response.status}",
                    )

                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            results = []
            snippets = soup.find_all("div", class_="snippet") or soup.find_all("div", class_="result")

            for div in snippets[:max_results]:
                try:
                    title_elem = div.find("div", class_="title") or div.find("a")
                    link_elem = div.find("a")
                    snippet_elem = div.find("div", class_="search-snippet-content") or div.find("p")

                    if title_elem and link_elem:
                        url = link_elem.get("href", "")
                        if url.startswith("http"):
                            results.append(
                                SearchResult(
                                    title=title_elem.get_text(strip=True),
                                    url=url,
                                    snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                    source="brave_search_free",
                                )
                            )
                except Exception:
                    continue

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="brave_search_free",
            )
        except Exception as exc:
            logger.error("Brave free search error: %s", exc)
            return SearchResponse(query=query, results=[], provider="brave_search_free", error=str(exc))

    async def _search_mojeek(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        try:
            url = "https://www.mojeek.com/search"
            params = {"q": query}
            headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.8,*/*;q=0.8"}

            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="mojeek",
                        error=f"HTTP {response.status}",
                    )

                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            results = []
            result_items = soup.select('li[class^="r"]')

            for li in result_items[:max_results]:
                try:
                    title_elem = li.find("a", class_="title")
                    snippet_elem = li.find("p", class_="s")
                    if title_elem:
                        href = title_elem.get("href", "")
                        if href.startswith("http"):
                            results.append(
                                SearchResult(
                                    title=title_elem.get_text(strip=True),
                                    url=href,
                                    snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                    source="mojeek",
                                )
                            )
                except Exception:
                    continue

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="mojeek",
            )
        except Exception as exc:
            logger.error("Mojeek search error: %s", exc)
            return SearchResponse(query=query, results=[], provider="mojeek", error=str(exc))

    async def _search_wikipedia(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        try:
            search_url = "https://en.wikipedia.org/w/api.php"
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": max_results,
            }
            headers = {"User-Agent": "AI-Karen-Search-Plugin/1.0 (https://ai-karen.ai; contact@ai-karen.ai)"}

            async with self.session.get(search_url, params=search_params, headers=headers) as response:
                if response.status != 200:
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="wikipedia",
                        error=f"HTTP {response.status}",
                    )

                search_data = await response.json()
                page_titles = [item.get("title") for item in search_data.get("query", {}).get("search", [])]

            if page_titles:
                extract_params = {
                    "action": "query",
                    "titles": "|".join(page_titles[:max_results]),
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "format": "json",
                    "exsectionformat": "plain",
                }

                async with self.session.get(search_url, params=extract_params, headers=headers) as response:
                    if response.status != 200:
                        return await self._wikipedia_fallback_results(search_data, query)

                    extract_data = await response.json()

                results = []
                pages = extract_data.get("query", {}).get("pages", {})

                for item in search_data.get("query", {}).get("search", []):
                    title = item.get("title", "")
                    page_id = str(item.get("pageid"))
                    snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text()
                    content = pages.get(page_id, {}).get("extract") if page_id in pages else None

                    results.append(
                        SearchResult(
                            title=title,
                            url=f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                            snippet=snippet,
                            content=content,
                            source="wikipedia",
                        )
                    )

                return SearchResponse(
                    query=query,
                    results=results,
                    total_results=len(results),
                    provider="wikipedia",
                )

            return SearchResponse(query=query, results=[], provider="wikipedia")
        except Exception as exc:
            logger.error("Wikipedia search error: %s", exc)
            return SearchResponse(query=query, results=[], provider="wikipedia", error=str(exc))

    async def _wikipedia_fallback_results(self, search_data: Any, query: str) -> SearchResponse:
        results = []
        for item in search_data.get("query", {}).get("search", []):
            title = item.get("title", "")
            snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text()
            results.append(
                SearchResult(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                    snippet=snippet,
                    source="wikipedia",
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider="wikipedia",
        )

    async def _search_tavily(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        config = self.registry.get_config("tavily")
        api_key = self.settings.get("tavily_api_key") or config.get("api_key")
        api_url = config.get("api_url", "https://api.tavily.com/search")

        try:
            days = None
            if time_range:
                time_map = {"d": 1, "w": 7, "m": 30, "y": 365}
                days = time_map.get(time_range.lower())

            payload = {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": True,
                "include_images": False,
            }
            if days:
                payload["days"] = days

            async with self.session.post(api_url, json=payload) as response:
                data = await response.json()

            if response.status != 200:
                error_msg = data.get("message", f"HTTP {response.status}")
                return SearchResponse(query=query, results=[], provider="tavily", error=error_msg)

            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content") or "",
                        content=item.get("raw_content"),
                        published_date=item.get("published_date"),
                        source="tavily",
                    )
                )

            return SearchResponse(
                query=query,
                results=results,
                total_results=data.get("num_results"),
                search_time=data.get("answer_time_seconds"),
                provider="tavily",
            )
        except Exception as exc:
            logger.error("Tavily search error: %s", exc, exc_info=True)
            return SearchResponse(query=query, results=[], provider="tavily", error=str(exc))

    async def _search_google(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        config = self.registry.get_config("google_custom_search")
        api_key = self.settings.get("google_api_key") or config.get("api_key")
        cx_id = self.settings.get("google_cx_id") or config.get("cx_id")
        api_url = config.get("api_url", "https://www.googleapis.com/customsearch/v1")

        try:
            params = {"key": api_key, "cx": cx_id, "q": query, "num": max_results}
            if time_range:
                params["dateRestrict"] = time_range

            async with self.session.get(api_url, params=params) as response:
                data = await response.json()

            if response.status != 200:
                error_msg = data.get("error", {}).get("message", f"HTTP {response.status}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider="google_custom_search",
                    error=error_msg,
                )

            results = []
            for item in data.get("items", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        source="google_custom_search",
                    )
                )

            return SearchResponse(
                query=query,
                results=results,
                total_results=data.get("searchInformation", {}).get("totalResults"),
                search_time=data.get("searchInformation", {}).get("searchTime"),
                provider="google_custom_search",
            )
        except Exception as exc:
            logger.error("Google Custom Search error: %s", exc, exc_info=True)
            return SearchResponse(
                query=query,
                results=[],
                provider="google_custom_search",
                error=str(exc),
            )

    async def _search_startpage(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> SearchResponse:
        try:
            url = "https://www.startpage.com/sp/search"
            data = {"query": query, "cat": "web", "language": "english"}
            headers = {"Origin": "https://www.startpage.com", "Referer": "https://www.startpage.com/"}

            async with self.session.post(url, data=data, headers=headers) as response:
                if response.status != 200:
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="startpage",
                        error=f"HTTP {response.status}",
                    )

                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            results = []
            items = soup.find_all("div", class_="w-gl__result")

            for item in items[:max_results]:
                try:
                    title_elem = item.find("a", class_="w-gl__result-title")
                    link_elem = title_elem if title_elem else item.find("a")
                    snippet_elem = item.find("p", class_="w-gl__description")

                    if link_elem:
                        href = link_elem.get("href", "")
                        if href.startswith("http"):
                            results.append(
                                SearchResult(
                                    title=link_elem.get_text(strip=True),
                                    url=href,
                                    snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                    source="startpage",
                                )
                            )
                except Exception as exc:
                    logger.debug("Failed to parse Startpage result: %s", exc)
                    continue

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="startpage",
            )
        except Exception as exc:
            logger.warning("Startpage search failed: %s", exc)
            return SearchResponse(query=query, results=[], provider="startpage", error=str(exc))

    def is_configured(self) -> bool:
        return any(self.registry.is_enabled(name) for name in self.registry.descriptors)

    def get_available_providers(self) -> List[str]:
        return [name for name in self.registry.descriptors if self.registry.is_enabled(name)]
