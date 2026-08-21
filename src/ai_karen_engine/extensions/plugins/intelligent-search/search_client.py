"""
Web search client with support for multiple search providers.

Supported providers:
- duckduckgo: Free, no API key needed
- tavily: AI-focused search with free tier
- google_custom_search: Google Custom Search JSON API (paid)
"""
import random
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

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

    Automatically falls back to DuckDuckGo if configured providers fail.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize search client.

        Args:
            settings: Configuration dict with provider settings
        """
        self.settings = settings or {}
        self.session: Optional[aiohttp.ClientSession] = None

        # Provider configurations
        self.providers = {
            "duckduckgo": {
                "enabled": True,
                "priority": 100,  # Highest priority free provider
            },
            "searxng": {
                "enabled": True,
                "priority": 95,
                "instances": self.settings.get("searxng_instances", [
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
                ]),
            },
            "brave_search": {
                "enabled": bool(self.settings.get("brave_api_key")),
                "api_key": self.settings.get("brave_api_key"),
                "api_url": "https://api.search.brave.com/res/v1/web/search",
                "priority": 92,
            },
            "brave_search_free": {
                "enabled": True,
                "priority": 91,  # High priority free scraper
            },
            "tavily": {
                "enabled": bool(self.settings.get("tavily_api_key")),
                "api_key": self.settings.get("tavily_api_key"),
                "api_url": "https://api.tavily.com/search",
                "priority": 90,
            },
            "mojeek": {
                "enabled": True,
                "priority": 88,  # Reliable alternative scraper
            },
            "wikipedia": {
                "enabled": True,
                "priority": 85,  # Reliable fallback for general knowledge
            },
            "startpage": {
                "enabled": True,
                "priority": 87,
            },
            "google_custom_search": {
                "enabled": bool(
                    self.settings.get("google_api_key")
                    and self.settings.get("google_cx_id")
                ),
                "api_key": self.settings.get("google_api_key"),
                "cx_id": self.settings.get("google_cx_id"),
                "api_url": "https://www.googleapis.com/customsearch/v1",
                "priority": 80,
            },
        }

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/114.0",
        ]

        # Sort providers by priority
        self._sorted_providers = sorted(
            [
                (name, config)
                for name, config in self.providers.items()
                if config.get("enabled", False)
            ],
            key=lambda x: x[1].get("priority", 0),
            reverse=True,
        )

    async def _fetch_content_from_url(self, url: str, max_length: int = 2000) -> Optional[str]:
        """Fetch and extract text content from a URL."""
        try:
            headers = {"User-Agent": random.choice(self.user_agents)}
            async with self.session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    return None
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text content
            text = soup.get_text(separator=" ", strip=True)

            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "..."

            return text
        except Exception as e:
            logger.debug(f"Failed to fetch content from {url}: {e}")
            return None

    async def __aenter__(self):
        """Async context manager entry."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
            self.session = None

    async def search(
        self,
        query: str,
        max_results: int = 5,
        time_range: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs,
    ) -> SearchResponse:
        """
        Perform web search.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            time_range: Time filter (e.g., "d" for day, "w" for week, "m" for month, "y" for year)
            provider: Force specific provider (falls back to others if fails)
            **kwargs: Additional provider-specific parameters

        Returns:
            SearchResponse with results or error
        """
        if not query or not query.strip():
            return SearchResponse(
                query=query,
                results=[],
                provider="none",
                error="Empty query",
            )

        # Use specific provider if requested, otherwise try all by priority
        if provider:
            if provider in self.providers and self.providers[provider]["enabled"]:
                result = await self._search_with_provider(
                    provider,
                    query,
                    max_results,
                    time_range,
                    **kwargs,
                )
                return result
            else:
                # Fallback to highest priority provider
                logger.warning(
                    f"Requested provider '{provider}' not available, falling back",
                )

        # Try providers in priority order
        last_error = None
        for provider_name, config in self._sorted_providers:
            try:
                logger.debug(
                    f"Attempting search with provider: {provider_name}",
                    extra={"provider": provider_name, "query": query},
                )
                result = await self._search_with_provider(
                    provider_name,
                    query,
                    max_results,
                    time_range,
                    **kwargs,
                )

                if not result.error and result.results:
                    return result

                last_error = result.error or "No results"
                logger.debug(
                    f"Provider {provider_name} returned no results",
                    extra={"provider": provider_name, "error": last_error},
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Provider {provider_name} failed: {e}",
                    extra={"provider": provider_name, "error": str(e)},
                )
                continue

        # All providers failed
        return SearchResponse(
            query=query,
            results=[],
            provider="none",
            error=f"All providers failed. Last error: {last_error}",
        )

    async def _search_with_provider(
        self,
        provider_name: str,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs,
    ) -> SearchResponse:
        """Search with specific provider."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        if provider_name == "duckduckgo":
            return await self._search_duckduckgo(query, max_results, **kwargs)
        elif provider_name == "brave_search":
            return await self._search_brave_api(query, max_results, **kwargs)
        elif provider_name == "brave_search_free":
            return await self._search_brave_free(query, max_results, **kwargs)
        elif provider_name == "searxng":
            return await self._search_searxng(query, max_results, time_range, **kwargs)
        elif provider_name == "tavily":
            return await self._search_tavily(query, max_results, time_range, **kwargs)
        elif provider_name == "mojeek":
            return await self._search_mojeek(query, max_results, **kwargs)
        elif provider_name == "wikipedia":
            return await self._search_wikipedia(query, max_results, **kwargs)
        elif provider_name == "google_custom_search":
            return await self._search_google(query, max_results, time_range, **kwargs)
        elif provider_name == "startpage":
            return await self._search_startpage(query, max_results, **kwargs)
        else:
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
        **kwargs,
    ) -> SearchResponse:
        """
        Search using DuckDuckGo HTML parsing (no API key required).

        Note: This is a scraping approach and may be less reliable than official APIs.
        """
        try:
            url = "https://html.duckduckgo.com/html/"
            params = {
                "q": query,
                "kl": "us-en",
            }

            # Add headers to avoid bot detection
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://duckduckgo.com/",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }

            async with self.session.get(url, params=params, headers=headers) as response:
                # Accept 200 and 202 (DuckDuckGo sometimes returns 202)
                if response.status not in (200, 202):
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="duckduckgo",
                        error=f"HTTP {response.status}",
                    )

                html = await response.text()

            # Parse HTML
            soup = BeautifulSoup(html, "html.parser")
            results = []

            # Find all result divs - try multiple selectors
            result_divs = soup.find_all("div", class_="result")

            if not result_divs:
                # Try alternative selectors
                result_divs = soup.find_all("div", class_="web-result")

            for i, div in enumerate(result_divs[:max_results]):
                try:
                    # Try multiple selectors for title
                    title_elem = (
                        div.find("a", class_="result__a")
                        or div.find("a", class_="result__url")
                        or div.find("a")
                    )
                    snippet_elem = div.find("a", class_="result__snippet")

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    url = title_elem.get("href", "")
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                    if title and url:
                        # Try to fetch content for the first result or if it's a high-quality result
                        content = None
                        if len(results) < 2 and url.startswith(('http://', 'https://')):
                            content = await self._fetch_content_from_url(url)

                        results.append(
                            SearchResult(
                                title=title,
                                url=url,
                                snippet=snippet,
                                content=content,
                                source="duckduckgo",
                            )
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse DuckDuckGo result {i}: {e}",
                    )
                    continue

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="duckduckgo",
            )

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="duckduckgo",
                error=str(e),
            )

    async def _search_searxng(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs,
    ) -> SearchResponse:
        """Search using SearxNG with instance rotation fallback."""
        instances = self.providers["searxng"]["instances"]
        # Shuffle instances to distribute load
        shuffled_instances = list(instances)
        random.shuffle(shuffled_instances)

        last_error = "All instances failed"
        
        for instance_url in shuffled_instances[:3]:  # Try up to 3 instances
            try:
                url = f"{instance_url.rstrip('/')}/search"
                params = {
                    "q": query,
                    "format": "json",
                    "safesearch": 1,
                    "categories": "general",
                }
                
                if time_range:
                    # Convert standard time range to SearxNG format
                    time_map = {"d": "day", "w": "week", "m": "month", "y": "year"}
                    params["time_range"] = time_map.get(time_range.lower(), time_range)

                headers = {"User-Agent": random.choice(self.user_agents)}

                async with self.session.get(url, params=params, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        last_error = f"HTTP {response.status} from {instance_url}"
                        continue
                        
                    data = await response.json()
                    results = []
                    
                    for item in data.get("results", [])[:max_results]:
                        content = item.get("content")
                        results.append(
                            SearchResult(
                                title=item.get("title", ""),
                                url=item.get("url", ""),
                                snippet=content or "",
                                content=content,
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
                    else:
                        last_error = f"No results from {instance_url}"
            except Exception as e:
                last_error = f"Error from {instance_url}: {str(e)}"
                logger.debug(f"SearxNG instance {instance_url} failed: {e}")
                continue

        return SearchResponse(
            query=query,
            results=[],
            provider="wikipedia",
            error=last_error,
        )

    async def _search_brave_api(
        self,
        query: str,
        max_results: int,
        **kwargs,
    ) -> SearchResponse:
        """Search using Brave Search API."""
        api_key = self.providers["brave_search"]["api_key"]
        api_url = self.providers["brave_search"]["api_url"]

        try:
            params = {
                "q": query,
                "count": max_results,
            }
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            }

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
                    content = item.get("description")
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=content or "",
                            content=content,
                            source="brave_search",
                        )
                    )
                    
                return SearchResponse(
                    query=query,
                    results=results,
                    total_results=len(results),
                    provider="brave_search",
                )
        except Exception as e:
            logger.error(f"Brave API search error: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="brave_search",
                error=str(e),
            )

    async def _search_brave_free(
        self,
        query: str,
        max_results: int,
        **kwargs,
    ) -> SearchResponse:
        """Search using Brave Search scraping (free)."""
        try:
            url = "https://search.brave.com/search"
            params = {"q": query}
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
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
            
            # Brave uses 'snippet' or 'result' classes
            snippets = soup.find_all("div", class_="snippet") or soup.find_all("div", class_="result")
            
            for div in snippets[:max_results]:
                try:
                    title_elem = div.find("div", class_="title") or div.find("a")
                    link_elem = div.find("a")
                    snippet_elem = div.find("div", class_="search-snippet-content") or div.find("p")
                    
                    if title_elem and link_elem:
                        url = link_elem.get("href", "")
                        if not url.startswith("http"):
                            continue
                            
                        # Try to fetch content for the first result
                        content = None
                        if len(results) < 2 and url.startswith(('http://', 'https://')):
                            content = await self._fetch_content_from_url(url)

                        results.append(
                            SearchResult(
                                title=title_elem.get_text(strip=True),
                                url=url,
                                snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                content=content,
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
        except Exception as e:
            logger.error(f"Brave free search error: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="brave_search_free",
                error=str(e),
            )

    async def _search_mojeek(
        self,
        query: str,
        max_results: int,
        **kwargs,
    ) -> SearchResponse:
        """Search using Mojeek scraping (free)."""
        try:
            url = "https://www.mojeek.com/search"
            params = {"q": query}
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

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
            
            # Mojeek results are in li with classes like r1, r2, etc.
            result_items = soup.select('li[class^="r"]')
            
            for li in result_items[:max_results]:
                try:
                    title_elem = li.find("a", class_="title")
                    snippet_elem = li.find("p", class_="s")
                    
                    if title_elem:
                        url = title_elem.get("href", "")
                        # Try to fetch content for the first result
                        content = None
                        if len(results) < 2 and url.startswith(('http://', 'https://')):
                            content = await self._fetch_content_from_url(url)

                        results.append(
                            SearchResult(
                                title=title_elem.get_text(strip=True),
                                url=url,
                                snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                content=content,
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
        except Exception as e:
            logger.error(f"Mojeek search error: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="mojeek",
                error=str(e),
            )

    async def _search_wikipedia(
        self,
        query: str,
        max_results: int,
        **kwargs,
    ) -> SearchResponse:
        """Search using Wikipedia API (very reliable fallback)."""
        try:
            # First, search for pages
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
                    logger.warning(f"Wikipedia search API failed with status {response.status}")
                    return SearchResponse(
                        query=query,
                        results=[],
                        provider="wikipedia",
                        error=f"HTTP {response.status}",
                    )

                search_data = await response.json()
                page_titles = [item.get("title") for item in search_data.get("query", {}).get("search", [])]

            # Now fetch extracts for the found pages
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
                        logger.warning(f"Wikipedia extract API failed with status {response.status}")
                        # Fall back to basic search results without content
                        return await self._wikipedia_fallback_results(search_data, query)

                    extract_data = await response.json()

                results = []
                pages = extract_data.get("query", {}).get("pages", {})

                for item in search_data.get("query", {}).get("search", []):
                    title = item.get("title", "")
                    page_id = str(item.get("pageid"))
                    snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text()

                    # Get extract content if available
                    content = None
                    if page_id in pages:
                        content = pages[page_id].get("extract")

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
            else:
                return SearchResponse(
                    query=query,
                    results=[],
                    provider="wikipedia",
                )

        except Exception as e:
            logger.error(f"Wikipedia search error: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="wikipedia",
                error=str(e),
            )

    async def _wikipedia_fallback_results(self, search_data, query: str) -> SearchResponse:
        """Fallback to basic search results without content."""
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
        **kwargs,
    ) -> SearchResponse:
        """Search using Tavily API."""
        api_key = self.providers["tavily"]["api_key"]
        api_url = self.providers["tavily"]["api_url"]

        try:
            # Convert time_range to days for Tavily
            days = None
            if time_range:
                time_map = {"d": 1, "w": 7, "m": 30, "y": 365}
                days = time_map.get(time_range.lower(), None)

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
                return SearchResponse(
                    query=query,
                    results=[],
                    provider="tavily",
                    error=error_msg,
                )

            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
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

        except Exception as e:
            logger.error(f"Tavily search error: {e}", exc_info=True)
            return SearchResponse(
                query=query,
                results=[],
                provider="tavily",
                error=str(e),
            )

    async def _search_google(
        self,
        query: str,
        max_results: int,
        time_range: Optional[str] = None,
        **kwargs,
    ) -> SearchResponse:
        """Search using Google Custom Search API."""
        api_key = self.providers["google_custom_search"]["api_key"]
        cx_id = self.providers["google_custom_search"]["cx_id"]
        api_url = self.providers["google_custom_search"]["api_url"]

        try:
            params = {
                "key": api_key,
                "cx": cx_id,
                "q": query,
                "num": max_results,
            }

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

        except Exception as e:
            logger.error(f"Google Custom Search error: {e}", exc_info=True)
            return SearchResponse(
                query=query,
                results=[],
                provider="google_custom_search",
                error=str(e),
            )


    def is_configured(self) -> bool:
        """Check if any provider is configured."""
        return any(config.get("enabled", False) for config in self.providers.values())

    def get_available_providers(self) -> List[str]:
        """Get list of enabled providers."""
        return [
            name
            for name, config in self.providers.items()
            if config.get("enabled", False)
        ]
    async def _search_startpage(
        self,
        query: str,
        max_results: int,
        **kwargs,
    ) -> SearchResponse:
        """Search using Startpage (Google results proxy)."""
        try:
            url = "https://www.startpage.com/sp/search"
            data = {
                "query": query,
                "cat": "web",
                "language": "english",
            }
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Origin": "https://www.startpage.com",
                "Referer": "https://www.startpage.com/",
            }

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
            
            # Startpage uses 'w-gl__result' or similar
            items = soup.find_all("div", class_="w-gl__result")
            
            for item in items[:max_results]:
                try:
                    title_elem = item.find("a", class_="w-gl__result-title")
                    link_elem = title_elem if title_elem else item.find("a")
                    snippet_elem = item.find("p", class_="w-gl__description")
                    
                    if link_elem:
                        url = link_elem.get("href", "")
                        if not url.startswith("http"):
                            continue
                            
                        results.append(
                            SearchResult(
                                title=link_elem.get_text(strip=True),
                                url=url,
                                snippet=snippet_elem.get_text(strip=True) if snippet_elem else "",
                                source="startpage",
                            )
                        )
                except Exception as e:
                    logger.debug(f"Failed to parse Startpage result: {e}")
                    continue
            
            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="startpage",
            )
        except Exception as e:
            logger.warning(f"Startpage search failed: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider="startpage",
                error=str(e),
            )
