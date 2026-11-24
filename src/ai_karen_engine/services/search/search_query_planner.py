import logging
from typing import List, Dict, Any
import re

logger = logging.getLogger(__name__)

class SearchQueryPlanner:
    """
    Search Planning Engine.
    Responsibilities: Query expansion, intent classification, and search mode detection.
    """

    @staticmethod
    def is_historical_or_encyclopedic(query: str) -> bool:
        """Determine if a query has historical or encyclopedic intent."""
        q = query.lower()
        indicators = [
            "history", "historical", "origin", "origins", "who was", "who is",
            "biography", "founded", "established", "independence", "ancient",
            "timeline", "encyclopedia", "what was", "what is",
        ]
        return any(term in q for term in indicators)

    @staticmethod
    def normalize_query(query: str) -> str:
        """Strip conversational prefixes and trailing punctuation for search retrieval."""
        cleaned = query.strip()
        cleaned = re.sub(r"[?!.]+$", "", cleaned).strip()
        patterns = [
            r"^(?:what(?:'s|\s+is|\s+was)?(?:\s+the)?)\s+",
            r"^(?:tell\s+me\s+about(?:\s+the)?)\s+",
            r"^(?:can\s+you\s+tell\s+me\s+about(?:\s+the)?)\s+",
            r"^(?:give\s+me\s+(?:a|the)\s+overview\s+of)\s+",
            r"^(?:who\s+(?:is|was)(?:\s+the)?)\s+",
            r"^(?:search\s+(?:for)?)\s+",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                remainder = cleaned[match.end():].strip()
                if remainder:
                    cleaned = remainder
                    break
        return cleaned

    def generate_queries(self, query: str) -> List[str]:
        """Expand a single user query into targeted search queries."""
        base = query.strip()
        if not base:
            return []

        # Keep original query first to preserve all consumer/caller contracts
        expansions = [base]

        # Conversational query normalization: if the query contains conversational
        # filler (e.g. "Whats the history of jamaica"), add the concise topic query.
        normalized = self.normalize_query(base)
        if normalized and normalized.lower() != base.lower():
            expansions.append(normalized)

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
