"""
AG-UI enhanced memory manager that extends the existing memory system
with modern data visualization and grid components.
"""

import json
import logging
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.memory.memory_runtime_manager import (
    get_metrics,
    recall_context,
    update_memory,
)

# Import NLP services - canonical adapters provide spaCy and DistilBERT
try:
    from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
    from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService

    spacy_service_manager = SpacyService()
    distilbert_service_manager = DistilBertService()
except ImportError:
    spacy_service_manager = None
    distilbert_service_manager = None

logger = logging.getLogger("kari.memory.ag_ui_manager")


@dataclass
class MemoryGridRow:
    """Data model for AG-UI memory grid rows."""

    id: str
    content: str
    type: str  # 'fact', 'preference', 'context'
    confidence: float
    last_accessed: str
    relevance_score: float
    semantic_cluster: str
    relationships: List[str]
    timestamp: int
    user_id: str
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None


@dataclass
class MemoryNetworkNode:
    """Data model for AG-UI network visualization nodes."""

    id: str
    label: str
    type: str
    confidence: float
    cluster: str
    size: int
    color: str


@dataclass
class MemoryNetworkEdge:
    """Data model for AG-UI network visualization edges."""

    source: str
    target: str
    weight: float
    type: str
    label: str


@dataclass
class MemoryAnalytics:
    """Analytics data for AG-UI charts."""

    total_memories: int
    memories_by_type: Dict[str, int]
    memories_by_cluster: Dict[str, int]
    confidence_distribution: List[Dict[str, Union[str, float]]]
    access_patterns: List[Dict[str, Union[str, int]]]
    relationship_stats: Dict[str, int]


class AGUIMemoryManager:
    """Enhanced memory manager with AG-UI data visualization capabilities."""

    def __init__(self):
        self._memory_cache: Dict[str, List[MemoryGridRow]] = {}
        self._analytics_cache: Dict[str, MemoryAnalytics] = {}

    async def get_memory_grid_data(
        self,
        user_ctx: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get memory data formatted for AG-UI grid display.

        Args:
            user_ctx: User context containing user_id, tenant_id, etc.
            filters: Optional filters for memory type, confidence, etc.
            limit: Maximum number of memories to return

        Returns:
            List of memory records formatted for AG-Grid
        """
        try:
            user_id = user_ctx.get("user_id", "anonymous")
            tenant_id = user_ctx.get("tenant_id")

            # Get raw memories from existing system
            if not tenant_id:
                logger.warning("Missing tenant_id in AG-UI memory grid request; returning empty result")
                return []

            recall_response = await recall_context(
                user_id=user_ctx,
                tenant_id=tenant_id,
                query="",
                top_k=limit,
            )
            raw_memories = recall_response.get("results", []) if isinstance(recall_response, dict) else []

            if not raw_memories:
                return []

            # Transform to AG-UI grid format
            grid_rows = []
            for i, memory in enumerate(raw_memories):
                # Extract memory details
                content = str(memory.get("result", memory.get("query", "")))
                memory_type = self._classify_memory_type(content)
                confidence = memory.get("confidence", 0.8)
                timestamp = memory.get("timestamp", 0)

                # Create semantic cluster (simplified)
                cluster = self._get_semantic_cluster(content)

                # Get relationships (simplified)
                relationships = self._get_memory_relationships(memory, raw_memories)

                row = MemoryGridRow(
                    id=f"mem_{user_id}_{i}",
                    content=content[:200] + "..." if len(content) > 200 else content,
                    type=memory_type,
                    confidence=confidence,
                    last_accessed=datetime.fromtimestamp(timestamp).isoformat()
                    if timestamp
                    else datetime.now().isoformat(),
                    relevance_score=memory.get("relevance_score", 0.5),
                    semantic_cluster=cluster,
                    relationships=relationships,
                    timestamp=timestamp,
                    user_id=user_id,
                    session_id=memory.get("session_id"),
                    tenant_id=tenant_id,
                )

                # Apply filters if provided
                if self._passes_filters(row, filters):
                    grid_rows.append(asdict(row))

            # Cache results
            cache_key = f"{user_id}_{tenant_id or 'missing'}"
            self._memory_cache[cache_key] = [MemoryGridRow(**row) for row in grid_rows]

            logger.info(
                f"Retrieved {len(grid_rows)} memories for AG-UI grid (user: {user_id})"
            )
            return grid_rows

        except Exception as e:
            logger.error(f"Error getting memory grid data: {e}")
            return []

    async def get_memory_network_data(
        self, user_ctx: Dict[str, Any], max_nodes: int = 50
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get memory relationship data for AG-UI network visualization.

        Args:
            user_ctx: User context
            max_nodes: Maximum number of nodes to include

        Returns:
            Dictionary with 'nodes' and 'edges' for network visualization
        """
        try:
            user_id = user_ctx.get("user_id", "anonymous")

            # Get cached or fresh memory data
            cache_key = f"{user_id}_{user_ctx.get('tenant_id', 'missing')}"
            if cache_key not in self._memory_cache:
                await self.get_memory_grid_data(user_ctx, limit=max_nodes)

            memories = self._memory_cache.get(cache_key, [])

            # Create nodes
            nodes = []
            node_clusters = {}

            for memory in memories[:max_nodes]:
                cluster = memory.semantic_cluster
                if cluster not in node_clusters:
                    node_clusters[cluster] = len(node_clusters)

                node = MemoryNetworkNode(
                    id=memory.id,
                    label=memory.content[:50] + "..."
                    if len(memory.content) > 50
                    else memory.content,
                    type=memory.type,
                    confidence=memory.confidence,
                    cluster=cluster,
                    size=int(memory.confidence * 20) + 5,  # Size based on confidence
                    color=self._get_cluster_color(node_clusters[cluster]),
                )
                nodes.append(asdict(node))

            # Create edges based on relationships
            edges = []
            for memory in memories[:max_nodes]:
                for related_id in memory.relationships:
                    if any(n["id"] == related_id for n in nodes):
                        edge = MemoryNetworkEdge(
                            source=memory.id,
                            target=related_id,
                            weight=0.5,  # Default weight
                            type="semantic",
                            label="related",
                        )
                        edges.append(asdict(edge))

            logger.info(
                f"Generated network with {len(nodes)} nodes and {len(edges)} edges"
            )
            return {"nodes": nodes, "edges": edges}

        except Exception as e:
            logger.error(f"Error getting memory network data: {e}")
            return {"nodes": [], "edges": []}

    async def get_memory_analytics(
        self, user_ctx: Dict[str, Any], timeframe_days: int = 30
    ) -> Dict[str, Any]:
        """
        Get memory analytics data for AG-UI charts.

        Args:
            user_ctx: User context
            timeframe_days: Number of days to analyze

        Returns:
            Analytics data formatted for AG-Charts
        """
        try:
            user_id = user_ctx.get("user_id", "anonymous")

            # Get memory data
            cache_key = f"{user_id}_{user_ctx.get('tenant_id', 'missing')}"
            if cache_key not in self._memory_cache:
                await self.get_memory_grid_data(user_ctx, limit=1000)

            memories = self._memory_cache.get(cache_key, [])

            # Filter by timeframe
            cutoff_time = datetime.now() - timedelta(days=timeframe_days)
            recent_memories = [
                m for m in memories if datetime.fromtimestamp(m.timestamp) > cutoff_time
            ]

            # Calculate analytics
            analytics = MemoryAnalytics(
                total_memories=len(recent_memories),
                memories_by_type=self._count_by_field(recent_memories, "type"),
                memories_by_cluster=self._count_by_field(
                    recent_memories, "semantic_cluster"
                ),
                confidence_distribution=self._get_confidence_distribution(
                    recent_memories
                ),
                access_patterns=self._get_access_patterns(recent_memories),
                relationship_stats=self._get_relationship_stats(recent_memories),
            )

            # Cache analytics
            self._analytics_cache[cache_key] = analytics

            logger.info(
                f"Generated analytics for {len(recent_memories)} recent memories"
            )
            return asdict(analytics)

        except Exception as e:
            logger.error(f"Error getting memory analytics: {e}")
            return {}

    async def search_memories(
        self,
        user_ctx: Dict[str, Any],
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Enhanced semantic search with AG-UI filtering interface using DistilBERT embeddings.

        Args:
            user_ctx: User context
            query: Search query
            filters: AG-UI filter conditions
            limit: Maximum results

        Returns:
            Filtered and ranked search results with semantic similarity scores
        """
        try:
            user_id = user_ctx.get("user_id", "anonymous")
            tenant_id = user_ctx.get("tenant_id")
            if not tenant_id:
                logger.warning("Missing tenant_id in AG-UI semantic search request; returning empty result")
                return []

            semantic_results = []
            recall_response = await recall_context(
                user_id=user_ctx,
                tenant_id=tenant_id,
                query=query,
                top_k=limit * 2,
            )
            raw_results = recall_response.get("results", []) if isinstance(recall_response, dict) else []
            for result in raw_results:
                semantic_results.append(
                    {
                        **result,
                        "semantic_score": self._calculate_semantic_similarity(
                            query, str(result.get("result", ""))
                        ),
                    }
                )

            if not semantic_results:
                return []

            # Transform to grid format with enhanced semantic information
            grid_data = []
            for i, memory in enumerate(semantic_results):
                content = str(memory.get("result", memory.get("query", "")))
                memory_type = await self._classify_memory_type_with_nlp(content)
                confidence = memory.get("confidence", 0.8)
                timestamp = memory.get("timestamp", 0)

                # Enhanced semantic cluster using spaCy
                cluster = await self._get_semantic_cluster_with_nlp(content)

                # Enhanced relationships using semantic similarity
                relationships = await self._get_semantic_relationships(
                    memory, semantic_results
                )

                row = MemoryGridRow(
                    id=f"mem_{user_id}_{i}",
                    content=content[:200] + "..." if len(content) > 200 else content,
                    type=memory_type,
                    confidence=confidence,
                    last_accessed=datetime.fromtimestamp(timestamp).isoformat()
                    if timestamp
                    else datetime.now().isoformat(),
                    relevance_score=memory.get(
                        "semantic_score", memory.get("relevance_score", 0.5)
                    ),
                    semantic_cluster=cluster,
                    relationships=relationships,
                    timestamp=timestamp,
                    user_id=user_id,
                    session_id=memory.get("session_id"),
                    tenant_id=user_ctx.get("tenant_id"),
                )

                grid_data.append(asdict(row))

            # Apply enhanced search ranking with semantic scores
            ranked_results = self._rank_search_results_with_semantics(grid_data, query)

            # Apply filters
            filtered_results = [
                result
                for result in ranked_results
                if self._passes_filters(MemoryGridRow(**result), filters)
            ]

            logger.info(
                f"Enhanced semantic search '{query}' returned {len(filtered_results)} results"
            )
            return filtered_results[:limit]

        except Exception as e:
            logger.error(f"Error in enhanced semantic search: {e}")
            return []

    async def update_memory_with_metadata(
        self,
        user_ctx: Dict[str, Any],
        query: str,
        result: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Enhanced memory update with additional metadata for AG-UI.

        Args:
            user_ctx: User context
            query: Memory query/content
            result: Memory result/data
            metadata: Additional metadata for visualization

        Returns:
            Success status
        """
        try:
            # Add AG-UI specific metadata
            enhanced_result = {
                "content": result,
                "metadata": metadata or {},
                "ag_ui_type": self._classify_memory_type(str(result)),
                "created_at": datetime.now().isoformat(),
                "confidence": metadata.get("confidence", 0.8) if metadata else 0.8,
            }

            # Use existing update_memory function
            success = await asyncio.to_thread(
                update_memory, user_ctx, query, enhanced_result
            )

            if success:
                # Clear cache to force refresh
                user_id = user_ctx.get("user_id", "anonymous")
                cache_key = f"{user_id}_{user_ctx.get('tenant_id', 'missing')}"
                self._memory_cache.pop(cache_key, None)
                self._analytics_cache.pop(cache_key, None)

                logger.info(f"Updated memory with AG-UI metadata for user {user_id}")

            return success

        except Exception as e:
            logger.error(f"Error updating memory with metadata: {e}")
            return False

    def _classify_memory_type(self, content: str) -> str:
        """Classify memory content into types for AG-UI display."""
        content_lower = content.lower()

        if any(
            word in content_lower
            for word in ["prefer", "like", "dislike", "favorite", "hate"]
        ):
            return "preference"
        elif any(
            word in content_lower
            for word in ["is", "are", "was", "were", "fact", "true"]
        ):
            return "fact"
        else:
            return "context"

    def _get_semantic_cluster(self, content: str) -> str:
        """Get semantic cluster for content (simplified implementation)."""
        content_lower = content.lower()

        if any(
            word in content_lower
            for word in ["code", "programming", "function", "class"]
        ):
            return "technical"
        elif any(
            word in content_lower for word in ["user", "person", "people", "team"]
        ):
            return "personal"
        elif any(
            word in content_lower for word in ["project", "task", "work", "business"]
        ):
            return "work"
        else:
            return "general"

    def _get_memory_relationships(
        self, memory: Dict[str, Any], all_memories: List[Dict[str, Any]]
    ) -> List[str]:
        """Get related memory IDs (simplified implementation)."""
        # This is a simplified implementation
        # In a real system, you'd use semantic similarity
        relationships = []
        memory_content = str(memory.get("result", memory.get("query", ""))).lower()

        for i, other_memory in enumerate(all_memories[:10]):  # Limit for performance
            if other_memory == memory:
                continue

            other_content = str(
                other_memory.get("result", other_memory.get("query", ""))
            ).lower()

            # Simple keyword overlap check
            memory_words = set(memory_content.split())
            other_words = set(other_content.split())
            overlap = len(memory_words.intersection(other_words))

            if overlap > 2:  # Threshold for relationship
                relationships.append(f"mem_{memory.get('user_id', 'anonymous')}_{i}")

        return relationships[:5]  # Limit relationships

    def _passes_filters(
        self, memory: MemoryGridRow, filters: Optional[Dict[str, Any]]
    ) -> bool:
        """Check if memory passes AG-UI filter conditions."""
        if not filters:
            return True

        for field, condition in filters.items():
            if field == "type" and condition != memory.type:
                return False
            elif field == "confidence_min" and memory.confidence < condition:
                return False
            elif field == "confidence_max" and memory.confidence > condition:
                return False
            elif field == "cluster" and condition != memory.semantic_cluster:
                return False

        return True

    def _get_cluster_color(self, cluster_index: int) -> str:
        """Get color for cluster visualization."""
        colors = [
            "#FF6B6B",
            "#4ECDC4",
            "#45B7D1",
            "#96CEB4",
            "#FFEAA7",
            "#DDA0DD",
            "#98D8C8",
        ]
        return colors[cluster_index % len(colors)]

    def _count_by_field(
        self, memories: List[MemoryGridRow], field: str
    ) -> Dict[str, int]:
        """Count memories by a specific field."""
        counts = {}
        for memory in memories:
            value = getattr(memory, field, "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts

    def _get_confidence_distribution(
        self, memories: List[MemoryGridRow]
    ) -> List[Dict[str, Union[str, float]]]:
        """Get confidence score distribution for charts."""
        bins = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}

        for memory in memories:
            confidence = memory.confidence
            if confidence < 0.2:
                bins["0.0-0.2"] += 1
            elif confidence < 0.4:
                bins["0.2-0.4"] += 1
            elif confidence < 0.6:
                bins["0.4-0.6"] += 1
            elif confidence < 0.8:
                bins["0.6-0.8"] += 1
            else:
                bins["0.8-1.0"] += 1

        return [{"range": k, "count": v} for k, v in bins.items()]

    def _get_access_patterns(
        self, memories: List[MemoryGridRow]
    ) -> List[Dict[str, Union[str, int]]]:
        """Get memory access patterns over time."""
        # Simplified implementation - group by day
        daily_counts = {}

        for memory in memories:
            date = datetime.fromtimestamp(memory.timestamp).strftime("%Y-%m-%d")
            daily_counts[date] = daily_counts.get(date, 0) + 1

        return [{"date": k, "count": v} for k, v in sorted(daily_counts.items())]

    def _get_relationship_stats(self, memories: List[MemoryGridRow]) -> Dict[str, int]:
        """Get statistics about memory relationships."""
        total_relationships = sum(len(memory.relationships) for memory in memories)
        connected_memories = sum(1 for memory in memories if memory.relationships)

        return {
            "total_relationships": total_relationships,
            "connected_memories": connected_memories,
            "isolated_memories": len(memories) - connected_memories,
            "avg_relationships": total_relationships / len(memories) if memories else 0,
        }

    def _rank_search_results(
        self, results: List[Dict[str, Any]], query: str
    ) -> List[Dict[str, Any]]:
        """Rank search results by relevance to query."""
        query_words = set(query.lower().split())

        def calculate_score(result):
            content_words = set(result["content"].lower().split())
            overlap = len(query_words.intersection(content_words))
            base_score = overlap / len(query_words) if query_words else 0
            confidence_boost = result["confidence"] * 0.3
            return base_score + confidence_boost

        # Sort by calculated relevance score
        return sorted(results, key=calculate_score, reverse=True)

    def _rank_search_results_with_semantics(
        self, results: List[Dict[str, Any]], query: str
    ) -> List[Dict[str, Any]]:
        """Enhanced ranking with semantic similarity scores."""
        query_words = set(query.lower().split())

        def calculate_enhanced_score(result):
            # Basic keyword overlap
            content_words = set(result["content"].lower().split())
            overlap = len(query_words.intersection(content_words))
            keyword_score = overlap / len(query_words) if query_words else 0

            # Semantic similarity score (if available)
            semantic_score = result.get("relevance_score", 0.5)

            # Confidence boost
            confidence_boost = result["confidence"] * 0.2

            # Combine scores with weights
            final_score = (
                (keyword_score * 0.4)
                + (semantic_score * 0.4)
                + (confidence_boost * 0.2)
            )
            return final_score

        # Sort by enhanced relevance score
        return sorted(results, key=calculate_enhanced_score, reverse=True)

    def _calculate_semantic_similarity(self, query: str, content: str) -> float:
        """Calculate semantic similarity between query and content."""
        try:
            # Simple word overlap similarity as fallback
            query_words = set(query.lower().split())
            content_words = set(content.lower().split())

            if not query_words or not content_words:
                return 0.0

            intersection = len(query_words.intersection(content_words))
            union = len(query_words.union(content_words))

            # Jaccard similarity
            similarity = intersection / union if union > 0 else 0.0
            return min(similarity, 1.0)

        except Exception as e:
            logger.warning(f"Error calculating semantic similarity: {e}")
            return 0.5

    async def _classify_memory_type_with_nlp(self, content: str) -> str:
        """Enhanced memory type classification using spaCy NLP."""
        try:
            # Try spaCy-based classification first
            if spacy_service_manager and spacy_service_manager.is_available():
                doc = await spacy_service_manager.process_text(content)
                if doc:
                    # Analyze linguistic patterns for better classification
                    content_lower = content.lower()

                    # Check for preference indicators with POS tagging
                    preference_patterns = [
                        "prefer",
                        "like",
                        "dislike",
                        "favorite",
                        "hate",
                        "love",
                    ]
                    if any(word in content_lower for word in preference_patterns):
                        return "preference"

                    # Check for factual statements using dependency parsing
                    fact_patterns = [
                        "is",
                        "are",
                        "was",
                        "were",
                        "fact",
                        "true",
                        "false",
                    ]
                    if any(word in content_lower for word in fact_patterns):
                        # Look for subject-predicate patterns
                        for token in doc:
                            if token.dep_ in [
                                "nsubj",
                                "nsubjpass",
                            ] and token.head.pos_ in ["VERB", "ADJ"]:
                                return "fact"

                    # Default to context for other cases
                    return "context"

            # Fallback to simple classification
            return self._classify_memory_type(content)

        except Exception as e:
            logger.warning(f"Error in NLP-based memory classification: {e}")
            return self._classify_memory_type(content)

    async def _get_semantic_cluster_with_nlp(self, content: str) -> str:
        """Enhanced semantic clustering using spaCy NLP."""
        try:
            # Try spaCy-based clustering first
            if spacy_service_manager and spacy_service_manager.is_available():
                doc = await spacy_service_manager.process_text(content)
                if doc:
                    # Analyze entities and keywords for better clustering
                    entities = [ent.label_ for ent in doc.ents]

                    # Technical cluster indicators
                    if any(label in entities for label in ["ORG", "PRODUCT"]) or any(
                        word in content.lower()
                        for word in [
                            "code",
                            "programming",
                            "api",
                            "function",
                            "class",
                            "software",
                            "tech",
                        ]
                    ):
                        return "technical"

                    # Personal cluster indicators
                    if any(label in entities for label in ["PERSON", "GPE"]) or any(
                        word in content.lower()
                        for word in [
                            "user",
                            "person",
                            "people",
                            "team",
                            "family",
                            "friend",
                        ]
                    ):
                        return "personal"

                    # Work cluster indicators
                    if any(
                        word in content.lower()
                        for word in [
                            "project",
                            "task",
                            "work",
                            "business",
                            "meeting",
                            "deadline",
                        ]
                    ):
                        return "work"

                    # Default to general
                    return "general"

            # Fallback to simple clustering
            return self._get_semantic_cluster(content)

        except Exception as e:
            logger.warning(f"Error in NLP-based semantic clustering: {e}")
            return self._get_semantic_cluster(content)

    async def _get_semantic_relationships(
        self, memory: Dict[str, Any], all_memories: List[Dict[str, Any]]
    ) -> List[str]:
        """Enhanced relationship detection using semantic similarity."""
        try:
            relationships = []
            memory_content = str(memory.get("result", memory.get("query", "")))

            # Try semantic similarity if DistilBERT is available
            if distilbert_service_manager and distilbert_service_manager.is_available():
                try:
                    # Get embedding for current memory
                    memory_embedding = await distilbert_service_manager.get_embeddings(
                        [memory_content]
                    )

                    if memory_embedding:
                        # Compare with other memories
                        for i, other_memory in enumerate(
                            all_memories[:20]
                        ):  # Limit for performance
                            if other_memory == memory:
                                continue

                            other_content = str(
                                other_memory.get(
                                    "result", other_memory.get("query", "")
                                )
                            )
                            other_embedding = (
                                await distilbert_service_manager.get_embeddings(
                                    [other_content]
                                )
                            )

                            if other_embedding:
                                # Calculate cosine similarity
                                similarity = self._cosine_similarity(
                                    memory_embedding[0], other_embedding[0]
                                )

                                if (
                                    similarity > 0.7
                                ):  # Threshold for semantic relationship
                                    relationships.append(
                                        f"mem_{memory.get('user_id', 'anonymous')}_{i}"
                                    )

                        return relationships[:5]  # Limit relationships

                except Exception as e:
                    logger.warning(f"DistilBERT relationship detection failed: {e}")

            # Fallback to simple keyword-based relationships
            return self._get_memory_relationships(memory, all_memories)

        except Exception as e:
            logger.warning(f"Error in semantic relationship detection: {e}")
            return self._get_memory_relationships(memory, all_memories)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            import math

            # Calculate dot product
            dot_product = sum(a * b for a, b in zip(vec1, vec2))

            # Calculate magnitudes
            magnitude1 = math.sqrt(sum(a * a for a in vec1))
            magnitude2 = math.sqrt(sum(a * a for a in vec2))

            # Avoid division by zero
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0

            # Calculate cosine similarity
            similarity = dot_product / (magnitude1 * magnitude2)
            return max(0.0, min(1.0, similarity))  # Clamp to [0, 1]

        except Exception as e:
            logger.warning(f"Error calculating cosine similarity: {e}")
            return 0.0


# Export the enhanced manager
__all__ = [
    "AGUIMemoryManager",
    "MemoryGridRow",
    "MemoryNetworkNode",
    "MemoryNetworkEdge",
    "MemoryAnalytics",
]
