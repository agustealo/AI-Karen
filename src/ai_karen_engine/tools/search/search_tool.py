"""
Search Tool for AI-Karen
Integrated from neuro_recall search capabilities with privacy-respecting web search
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
import aiohttp
import json
from urllib.parse import urlencode, quote_plus

from ai_karen_engine.services.search.web_search_defaults import DEFAULT_SEARXNG_INSTANCES

logger = logging.getLogger(__name__)


class SearchTool:
    """
    Privacy-respecting web search tool using SearxNG
    
    Features:
    - Multiple search engines via SearxNG
    - Privacy-focused (no tracking)
    - Configurable categories and filters
    - Safe search options
    - Time range filtering
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.searxng_url = self.config.get('searxng_url', 'http://localhost:8080')
        self.fallback_url = self.config.get('searxng_fallback_url') or (DEFAULT_SEARXNG_INSTANCES[0] if DEFAULT_SEARXNG_INSTANCES else None)
        self.timeout = self.config.get('timeout', 15)
        self.max_results = self.config.get('max_results', 10)
        self.default_category = self.config.get('default_category', 'general')
        self.default_language = self.config.get('default_language', 'en')
        
    async def search(
        self,
        query: str,
        num_results: int = 10,
        category: str = "general",
        language: str = "en",
        time_range: Optional[str] = None,
        safe_search: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Perform web search using SearxNG
        
        Args:
            query: Search query string
            num_results: Number of results to return (max 50)
            category: Search category (general, images, videos, news, etc.)
            language: Language code (en, es, fr, etc.)
            time_range: Time filter (day, week, month, year)
            safe_search: Safe search level (0=off, 1=moderate, 2=strict)
            
        Returns:
            List of search results with title, url, content, etc.
        """
        try:
            # Validate and sanitize inputs
            num_results = min(max(1, num_results), 50)
            safe_search = min(max(0, safe_search), 2)
            
            # Build search parameters
            params = {
                'q': query,
                'format': 'json',
                'categories': category,
                'language': language,
                'safesearch': safe_search
            }
            
            if time_range:
                params['time_range'] = time_range
                
            # Make request to SearxNG
            search_url = f"{self.searxng_url}/search"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                try:
                    async with session.get(search_url, params=params) as response:
                        if response.status != 200:
                            raise Exception(f"Primary search failed: {response.status}")
                        data = await response.json()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"Primary search failed ({e}), trying fallback: {self.fallback_url}")
                    # Fallback to public instance
                    fallback_search_url = f"{self.fallback_url}/search"
                    async with session.get(fallback_search_url, params=params) as response:
                        if response.status != 200:
                            raise Exception(f"Search failed with status {response.status} (including fallback)")
                        data = await response.json()
                    
            # Process results
            results = []
            raw_results = data.get('results', [])
            
            for i, result in enumerate(raw_results[:num_results]):
                processed_result = {
                    'title': result.get('title', ''),
                    'url': result.get('url', ''),
                    'content': result.get('content', ''),
                    'engine': result.get('engine', ''),
                    'category': result.get('category', category),
                    'score': result.get('score', 0),
                    'position': i + 1
                }
                
                # Add optional fields if present
                if 'publishedDate' in result:
                    processed_result['published_date'] = result['publishedDate']
                if 'img_src' in result:
                    processed_result['image_url'] = result['img_src']
                if 'thumbnail' in result:
                    processed_result['thumbnail'] = result['thumbnail']
                    
                results.append(processed_result)
            
            logger.info(f"Search completed: {len(results)} results for query '{query}'")
            return results
            
        except asyncio.TimeoutError:
            logger.error(f"Search timeout for query: {query}")
            raise Exception(f"Search request timed out after {self.timeout} seconds")
        except aiohttp.ClientError as e:
            logger.error(f"Search client error: {e}")
            raise Exception(f"Search request failed: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Search response parsing error: {e}")
            raise Exception("Invalid search response format")
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise Exception(f"Search failed: {str(e)}")
    
    async def search_images(
        self,
        query: str,
        num_results: int = 10,
        safe_search: int = 1
    ) -> List[Dict[str, Any]]:
        """Search for images"""
        return await self.search(
            query=query,
            num_results=num_results,
            category="images",
            safe_search=safe_search
        )
    
    async def search_news(
        self,
        query: str,
        num_results: int = 10,
        time_range: str = "week"
    ) -> List[Dict[str, Any]]:
        """Search for news articles"""
        return await self.search(
            query=query,
            num_results=num_results,
            category="news",
            time_range=time_range
        )
    
    async def search_videos(
        self,
        query: str,
        num_results: int = 10,
        safe_search: int = 1
    ) -> List[Dict[str, Any]]:
        """Search for videos"""
        return await self.search(
            query=query,
            num_results=num_results,
            category="videos",
            safe_search=safe_search
        )
    
    def get_supported_categories(self) -> List[str]:
        """Get list of supported search categories"""
        return [
            "general",
            "images", 
            "videos",
            "news",
            "map",
            "music",
            "it",
            "science",
            "files",
            "social media"
        ]
    
    def get_supported_languages(self) -> List[str]:
        """Get list of supported language codes"""
        return [
            "en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko",
            "ar", "hi", "nl", "sv", "da", "no", "fi", "pl", "tr", "he"
        ]
    
    def get_supported_time_ranges(self) -> List[str]:
        """Get list of supported time range filters"""
        return ["day", "week", "month", "year"]
