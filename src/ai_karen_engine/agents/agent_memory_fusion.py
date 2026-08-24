"""
Agent Memory Fusion service for integrating and consolidating agent memories.

.. deprecated::
    The legacy memory fusion service is deprecated. Memory operations are handled
    by ``ai_karen_engine.core.memory`` and ``ai_karen_engine.agent_medusa.adapters.memory_runtime_adapter``.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from ai_karen_engine.core.services.base import BaseService, ServiceConfig

warnings.warn(
    "ai_karen_engine.agents.agent_memory_fusion is deprecated. "
    "Use ai_karen_engine.core.memory instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


class AgentMemoryFusion(BaseService):
    """
    Agent Memory Fusion service for integrating and consolidating agent memories.
    
    This service provides capabilities to merge, consolidate, and optimize memories
    across different agents and memory systems.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_memory_fusion"))
        self._initialized = False
        self._memory_sources: Dict[str, str] = {}  # agent_id -> source_service_id
        self._fusion_strategies: Dict[str, Dict[str, Any]] = {}
        self._consolidated_memories: Dict[str, List[Dict[str, Any]]] = {}  # agent_id -> memories
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize the agent memory fusion service."""
        if self._initialized:
            return
            
        self._memory_sources = {}
        self._fusion_strategies = {
            "merge": {
                "description": "Merge memories with similar content",
                "similarity_threshold": 0.8
            },
            "deduplicate": {
                "description": "Remove duplicate memories",
                "exact_match": True
            },
            "compress": {
                "description": "Compress memory content to save space",
                "compression_ratio": 0.7
            },
            "prioritize": {
                "description": "Prioritize memories based on importance",
                "importance_factors": ["recency", "frequency", "relevance"]
            }
        }
        self._consolidated_memories = {}
        self._initialized = True
        logger.info("Agent memory fusion service initialized successfully")
    
    async def start(self) -> None:
        """Start the agent memory fusion service."""
        logger.info("Agent memory fusion service started")
    
    async def stop(self) -> None:
        """Stop the agent memory fusion service."""
        logger.info("Agent memory fusion service stopped")
    
    async def health_check(self) -> bool:
        """Check health of the agent memory fusion service."""
        return self._initialized
    
    async def register_memory_source(
        self, 
        agent_id: str, 
        source_service_id: str
    ) -> bool:
        """
        Register a memory source for an agent.
        
        Args:
            agent_id: Identifier of the agent
            source_service_id: Identifier of the memory source service
            
        Returns:
            True if registration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            self._memory_sources[agent_id] = source_service_id
            logger.info(f"Registered memory source {source_service_id} for agent {agent_id}")
            return True
    
    async def unregister_memory_source(self, agent_id: str) -> bool:
        """
        Unregister a memory source for an agent.
        
        Args:
            agent_id: Identifier of the agent
            
        Returns:
            True if unregistration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            if agent_id in self._memory_sources:
                del self._memory_sources[agent_id]
                logger.info(f"Unregistered memory source for agent {agent_id}")
                return True
            return False
    
    async def consolidate_memories(
        self, 
        agent_id: str, 
        memories: List[Dict[str, Any]],
        strategies: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Consolidate memories using specified strategies.
        
        Args:
            agent_id: Identifier of the agent
            memories: List of memories to consolidate
            strategies: List of fusion strategies to apply
            
        Returns:
            Consolidation result
        """
        if not self._initialized:
            await self.initialize()
            
        if strategies is None:
            strategies = ["merge", "deduplicate"]
        
        async with self._lock:
            # Apply each strategy in sequence
            result_memories = memories.copy()
            
            for strategy in strategies:
                if strategy in self._fusion_strategies:
                    result_memories = await self._apply_strategy(
                        strategy, 
                        result_memories
                    )
                else:
                    logger.warning(f"Unknown fusion strategy: {strategy}")
            
            # Store consolidated memories
            self._consolidated_memories[agent_id] = result_memories
            
            return {
                "status": "success",
                "agent_id": agent_id,
                "original_count": len(memories),
                "consolidated_count": len(result_memories),
                "strategies_applied": strategies,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _apply_strategy(
        self, 
        strategy: str, 
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Apply a fusion strategy to memories.
        
        Args:
            strategy: Name of the strategy to apply
            memories: List of memories to process
            
        Returns:
            Processed memories
        """
        if strategy == "merge":
            return await self._merge_similar_memories(memories)
        elif strategy == "deduplicate":
            return await self._deduplicate_memories(memories)
        elif strategy == "compress":
            return await self._compress_memories(memories)
        elif strategy == "prioritize":
            return await self._prioritize_memories(memories)
        else:
            return memories
    
    async def _merge_similar_memories(
        self, 
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Merge memories with similar content.
        
        Args:
            memories: List of memories to process
            
        Returns:
            Processed memories
        """
        # This is a simplified implementation
        # In a real system, this would use vector similarity or NLP techniques
        
        threshold = self._fusion_strategies["merge"]["similarity_threshold"]
        merged_memories = []
        processed_indices = set()
        
        for i, memory1 in enumerate(memories):
            if i in processed_indices:
                continue
                
            # Find similar memories
            similar_memories = [memory1]
            for j, memory2 in enumerate(memories[i+1:], i+1):
                if j in processed_indices:
                    continue
                    
                # Simple similarity check based on content overlap
                # In a real implementation, this would be more sophisticated
                content1 = str(memory1.get("content", "")).lower()
                content2 = str(memory2.get("content", "")).lower()
                
                # Calculate simple overlap ratio
                words1 = set(content1.split())
                words2 = set(content2.split())
                
                if words1 and words2:
                    intersection = words1.intersection(words2)
                    union = words1.union(words2)
                    similarity = len(intersection) / len(union)
                    
                    if similarity >= threshold:
                        similar_memories.append(memory2)
                        processed_indices.add(j)
            
            # Merge similar memories
            if len(similar_memories) > 1:
                merged_memory = self._create_merged_memory(similar_memories)
                merged_memories.append(merged_memory)
            else:
                merged_memories.append(memory1)
            
            processed_indices.add(i)
        
        return merged_memories
    
    def _create_merged_memory(
        self, 
        memories: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Create a merged memory from a list of similar memories.
        
        Args:
            memories: List of memories to merge
            
        Returns:
            Merged memory
        """
        # Take the most recent memory as base
        base_memory = max(memories, key=lambda m: m.get("created_at", ""))
        
        # Combine tags from all memories
        all_tags = set()
        for memory in memories:
            tags = memory.get("tags", [])
            if isinstance(tags, list):
                all_tags.update(tags)
        
        # Create merged memory
        merged_memory = base_memory.copy()
        merged_memory["tags"] = list(all_tags)
        merged_memory["merged_from"] = [m.get("memory_id", "") for m in memories]
        merged_memory["merged_at"] = datetime.utcnow().isoformat()
        merged_memory["merge_count"] = len(memories)
        
        return merged_memory
    
    async def _deduplicate_memories(
        self, 
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate memories.
        
        Args:
            memories: List of memories to process
            
        Returns:
            Processed memories
        """
        exact_match = self._fusion_strategies["deduplicate"]["exact_match"]
        unique_memories = []
        seen_contents = set()
        
        for memory in memories:
            content = str(memory.get("content", ""))
            
            if exact_match:
                # Check for exact content match
                if content not in seen_contents:
                    unique_memories.append(memory)
                    seen_contents.add(content)
            else:
                # Check for approximate content match
                is_duplicate = False
                content_lower = content.lower()
                
                for seen_content in seen_contents:
                    # Simple similarity check
                    if content_lower == seen_content.lower():
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    unique_memories.append(memory)
                    seen_contents.add(content)
        
        return unique_memories
    
    async def _compress_memories(
        self, 
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Compress memory content to save space.
        
        Args:
            memories: List of memories to process
            
        Returns:
            Processed memories
        """
        compression_ratio = self._fusion_strategies["compress"]["compression_ratio"]
        compressed_memories = []
        
        for memory in memories:
            compressed_memory = memory.copy()
            
            # Compress content by truncating if too long
            content = str(memory.get("content", ""))
            target_length = int(len(content) * compression_ratio)
            
            if len(content) > target_length:
                # Simple truncation with ellipsis
                compressed_memory["content"] = content[:target_length-3] + "..."
                compressed_memory["compressed"] = True
                compressed_memory["original_length"] = len(content)
                compressed_memory["compressed_length"] = target_length
            
            compressed_memories.append(compressed_memory)
        
        return compressed_memories
    
    async def _prioritize_memories(
        self, 
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Prioritize memories based on importance factors.
        
        Args:
            memories: List of memories to process
            
        Returns:
            Processed memories
        """
        importance_factors = self._fusion_strategies["prioritize"]["importance_factors"]
        
        # Calculate importance score for each memory
        memories_with_scores = []
        
        for memory in memories:
            score = 0.0
            
            # Recency factor (newer memories are more important)
            if "recency" in importance_factors:
                created_at = memory.get("created_at", "")
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at)
                        age = (datetime.utcnow() - created_dt).total_seconds()
                        # Newer memories have higher recency score
                        recency_score = max(0, 1 - (age / 86400))  # Normalize by day
                        score += recency_score
                    except (ValueError, TypeError):
                        pass
            
            # Frequency factor (more accessed memories are more important)
            if "frequency" in importance_factors:
                access_count = memory.get("access_count", 0)
                frequency_score = min(1, access_count / 10)  # Normalize by 10 accesses
                score += frequency_score
            
            # Add score to memory
            memory_with_score = memory.copy()
            memory_with_score["importance_score"] = score
            memories_with_scores.append(memory_with_score)
        
        # Sort by importance score (descending)
        memories_with_scores.sort(key=lambda m: m.get("importance_score", 0), reverse=True)
        
        return memories_with_scores
    
    async def get_consolidated_memories(
        self, 
        agent_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get consolidated memories for an agent.
        
        Args:
            agent_id: Identifier of the agent
            
        Returns:
            List of consolidated memories
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            return self._consolidated_memories.get(agent_id, []).copy()
    
    async def get_fusion_strategies(self) -> Dict[str, Dict[str, Any]]:
        """
        Get available fusion strategies.
        
        Returns:
            Dictionary of fusion strategy information
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            return self._fusion_strategies.copy()
    
    async def get_memory_sources(self) -> Dict[str, str]:
        """
        Get registered memory sources.
        
        Returns:
            Dictionary mapping agent IDs to memory source service IDs
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            return self._memory_sources.copy()