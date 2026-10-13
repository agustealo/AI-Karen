import logging
from typing import List, Dict, Any
import re

logger = logging.getLogger(__name__)

class SearchQueryPlanner:
    """
    Search Planning Engine.
    Responsibilities: Query expansion, intent classification, and search mode detection.
    """

    def generate_queries(self, query: str) -> List[str]:
        """Expand a single user query into multiple targeted search queries."""
        base = query.strip()
        if not base:
            return []

        # Ordinary queries should not acquire an unrelated news, comparison or
        # documentation intent. CORTEX/mode-specific retrieval owns expansion.
        expansions = [base]

        # Deduplicate and return
        return list(dict.fromkeys(expansions))

    def classify_mode(self, query: str) -> str:
        """Classify the search mode based on the user's intent."""
        q = query.lower()

        # News/Latest intent
        if any(x in q for x in ["latest", "today", "news", "breaking", "recent", "updates"]):
            return "news"

        # Documentation/Technical intent
        if any(x in q for x in ["docs", "api", "guide", "documentation", "how to", "manual"]):
            return "docs"

        # Deep research intent
        if any(x in q for x in ["deep", "research", "analyze", "comparison", "pros and cons", "detailed"]):
            return "deep_research"

        # Structured extraction intent
        if any(x in q for x in ["price", "specs", "specifications", "features", "list of"]):
            return "structured_extract"

        return "general"

    def get_retrieval_strategy(self, mode: str) -> Dict[str, Any]:
        """Define retrieval constraints based on the classified mode."""
        strategies = {
            "news": {"max_urls": 8, "depth": 1, "freshness_priority": True},
            "docs": {"max_urls": 3, "depth": 2, "source_priority": ["github.com", "readthedocs.io"]},
            "deep_research": {"max_urls": 12, "depth": 2, "comprehensive": True},
            "structured_extract": {"max_urls": 5, "depth": 1, "extract_structured": True},
            "general": {"max_urls": 5, "depth": 1}
        }
        return strategies.get(mode, strategies["general"])
