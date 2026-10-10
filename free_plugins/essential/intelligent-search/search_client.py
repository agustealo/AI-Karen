"""Compatibility adapter for the canonical web search client.

The implementation lives in ai_karen_engine.services.search.web_search_client.
Keep this module only so existing Intelligent Search plugin imports remain stable.
"""

from ai_karen_engine.services.search.web_search_client import (
    SearchResponse,
    SearchResult,
    WebSearchClient,
)

__all__ = ["SearchResult", "SearchResponse", "WebSearchClient"]
