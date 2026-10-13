import logging
from typing import List, Dict, Any
import hashlib
import re

logger = logging.getLogger(__name__)

class SearchResultProcessor:
    """
    Retrieval Intelligence Pipeline.
    Responsibilities: Chunking, deduplication, and semantic-ish ranking.
    """

    def process(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Process raw crawl results into ranked chunks."""
        if not results:
            return []

        # 1. Chunking
        chunks = self._chunk(results)
        
        # 2. Deduplication
        deduplicated = self._deduplicate(chunks)
        
        # 3. Ranking
        ranked = self._rank(deduplicated, query)
        
        # 4. Filter top results (limit to top 15 chunks for context window safety)
        return ranked[:15]

    def _chunk(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Split markdown content into logical chunks (paragraphs/sections)."""
        chunks = []
        for r in results:
            markdown = r.get("markdown", "")
            url = r.get("url", "")
            
            if not markdown:
                continue
                
            # Split by double newline (paragraphs/sections)
            sections = markdown.split("\n\n")
            for i, section in enumerate(sections):
                content = section.strip()
                if len(content) < 50:  # Skip very short fragments
                    continue
                    
                chunks.append({
                    "url": url,
                    "content": content,
                    "source_metadata": r.get("metadata", {}),
                    "chunk_id": f"{hashlib.md5(url.encode()).hexdigest()[:8]}_{i}"
                })
        return chunks

    def _deduplicate(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove near-identical chunks based on content hash."""
        seen_hashes = set()
        unique_chunks = []
        
        for c in chunks:
            # Simple content hash for exact match deduplication
            content_hash = hashlib.md5(c["content"].encode()).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique_chunks.append(c)
                
        return unique_chunks

    def _rank(self, chunks: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Rank chunks based on keyword relevance to the query."""
        query_words = set(re.findall(r"\\b\\w+\\b", query.casefold()))
        
        for c in chunks:
            score = self._calculate_score(c["content"], query_words)
            c["score"] = score
            
        # Sort by score descending
        return sorted(chunks, key=lambda x: x["score"], reverse=True)

    def _calculate_score(self, content: str, query_words: set) -> float:
        """Calculate a basic relevance score for a chunk."""
        # Match complete words only. Substrings such as "cat" in "catalog"
        # are not independent evidence of relevance.
        tokens = re.findall(r"\\b\\w+\\b", content.casefold())
        frequencies = {}
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
        score = sum(
            min(frequencies.get(word, 0), 5)
            for word in query_words
            if len(word) >= 3
        )
            
        # Boost for matches in headers (simplified)
        if content.startswith("#"):
            score *= 1.5
            
        return score
