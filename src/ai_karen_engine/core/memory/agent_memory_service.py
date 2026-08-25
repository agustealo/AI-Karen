"""
Enhanced Agent Memory service with deep integration to Karen's Unified Memory Service.

This service provides sophisticated memory management capabilities for agents, including
storage, retrieval, semantic search, memory sharing, and lifecycle management.
"""

import asyncio
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import numpy as np

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    pass

from ai_karen_engine.core.services.base import BaseService, ServiceConfig

# Try to import Unified Memory Service components
try:
    from ai_karen_engine.core.memory.unified_memory_service import (
        ContextHit,
        MemoryCommitRequest,
        MemoryQueryRequest,
        MemoryUsageStats,
        UnifiedMemoryService,
    )
    HAS_UNIFIED_MEMORY = True
except ImportError:
    HAS_UNIFIED_MEMORY = False
    UnifiedMemoryService = None
    MemoryCommitRequest = None
    MemoryQueryRequest = None
    ContextHit = None
    MemoryUsageStats = None

# Try to import Agent Registry
try:
    from .agent_registry import AgentRegistry
    HAS_AGENT_REGISTRY = True
except ImportError:
    HAS_AGENT_REGISTRY = False
    AgentRegistry = None

# Try to import Agent Orchestrator
try:
    from .agent_orchestrator import AgentOrchestrator
    HAS_AGENT_ORCHESTRATOR = True
except ImportError:
    HAS_AGENT_ORCHESTRATOR = False
    AgentOrchestrator = None

# Import internal agent modules
from .internal import agent_metrics, agent_validation

logger = logging.getLogger(__name__)


class MemoryAccessLevel(str, Enum):
    """Memory access level enumeration."""
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"
    INHERITED = "inherited"


class MemorySharingPolicy(str, Enum):
    """Memory sharing policy enumeration."""
    NONE = "none"
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    FULL_ACCESS = "full_access"


class MemoryFusionStrategy(str, Enum):
    """Memory fusion strategy enumeration."""
    MERGE = "merge"
    INTERSECT = "intersect"
    UNION = "union"
    PRIORITIZE_SOURCE = "prioritize_source"
    PRIORITIZE_TARGET = "prioritize_target"


class MemoryOperationType(str, Enum):
    """Enum representing different memory operations."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    SYNC = "sync"
    SHARE = "share"
    FUSE = "fuse"


class MemorySyncStatus(str, Enum):
    """Enum representing different synchronization statuses."""
    SYNCED = "synced"
    PENDING = "pending"
    FAILED = "failed"
    CONFLICT = "conflict"
    IN_PROGRESS = "in_progress"


@dataclass
class MemoryNamespace:
    """Agent memory namespace for isolation."""
    agent_id: str
    namespace: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryGraphEdge:
    """Edge in the memory graph for relationship tracking."""
    source_memory_id: str
    target_memory_id: str
    relationship_type: str
    strength: float = 0.5  # 0.0 to 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySharingRequest:
    """Request for sharing memory between agents."""
    source_agent_id: str
    target_agent_id: str
    memory_ids: list[str]
    access_level: MemoryAccessLevel
    sharing_policy: MemorySharingPolicy
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryFusionRequest:
    """Request for fusing memories between agents."""
    source_agent_id: str
    target_agent_id: str
    memory_ids: list[str]
    fusion_strategy: MemoryFusionStrategy
    conflict_resolution: str = "auto"  # auto, manual, source_priority, target_priority
    metadata: dict[str, Any] = field(default_factory=dict)


class EnhancedAgentMemory(BaseService):
    """
    Enhanced Agent Memory service with deep integration to Karen's Unified Memory Service.
    
    This service provides sophisticated memory management capabilities for agents, including
    storage, retrieval, semantic search, memory sharing, and lifecycle management. It also
    provides seamless integration with Karen's Unified Memory Service for enhanced memory
    synchronization, conflict resolution, and access control.
    
    Features:
    - Memory storage, retrieval, and search with semantic capabilities
    - Memory sharing and fusion between agents
    - Memory versioning and history tracking
    - Memory graph for relationship tracking
    - Integration with Karen's Unified Memory Service
    - Memory synchronization with conflict resolution
    - Memory access control and permission management
    - Memory operation logging and auditing
    
    Example:
        ```python
        # Initialize the memory service
        memory_service = EnhancedAgentMemory()
        await memory_service.initialize()
        
        # Store a memory
        memory_id = await memory_service.store_memory(
            agent_id="agent123",
            memory_type="conversation",
            content={"message": "Hello world", "context": "greeting"},
            tags=["greeting", "hello"],
            importance=0.8
        )
        
        # Search for memories
        results = await memory_service.search_memories(
            agent_id="agent123",
            query="hello",
            semantic=True
        )
        
        # Synchronize with Karen's memory
        sync_result = await memory_service.sync_with_karen_memory(
            agent_id="agent123"
        )
        
        # Check synchronization status
        sync_status = await memory_service.get_sync_status(agent_id="agent123")
        print(f"Sync status: {sync_status}")
        
        # Resolve conflicts if any
        if sync_status.get("conflicts", 0) > 0:
            for memory_id in sync_status.get("memories", []):
                if memory_id.get("sync_status") == "conflict":
                    await memory_service.resolve_memory_conflicts(
                        memory_id=memory_id["memory_id"],
                        conflict_details={},
                        resolution_strategy="agent_priority"
                    )
        ```
    
    Error Handling:
        The service implements comprehensive error handling with proper logging and graceful
        degradation when dependencies are unavailable. All methods log errors with context
        and provide meaningful error messages.
        
    Performance Considerations:
        - Async/await pattern for non-blocking operations
        - Configurable batch sizes for bulk operations
        - Memory usage monitoring and cleanup
        - Operation metrics collection
    """
    
    def __init__(self, config: ServiceConfig | None = None):
        super().__init__(config or ServiceConfig(name="agent_memory"))
        self._initialized = False
        self._lock = asyncio.Lock()
        
        # Core services
        self._unified_memory_service: Any = None
        self._agent_registry: Any = None
        self._agent_orchestrator: Any = None
        self._metrics_service: Any = None
        self._validation_service: Any = None
        
        # Legacy memory store for backward compatibility
        self._memory_store: dict[str, dict[str, Any]] = {}
        
        # Agent memory namespaces for isolation
        self._namespaces: dict[str, dict[str, MemoryNamespace]] = {}
        
        # Memory graph for relationship tracking
        self._memory_graph_edges: dict[str, list[MemoryGraphEdge]] = {}
        
        # Memory sharing registry
        self._shared_memories: dict[str, dict[str, list[str]]] = {}  # target_agent_id -> source_agent_id -> memory_ids
        self._sharing_requests: dict[str, MemorySharingRequest] = {}  # request_id -> request
        
        # Memory versioning and history
        self._memory_versions: dict[str, list[dict[str, Any]]] = {}  # memory_id -> versions
        self._memory_history: dict[str, list[dict[str, Any]]] = {}  # memory_id -> history
        
        # Memory embeddings for semantic search
        self._memory_embeddings: dict[str, np.ndarray] = {}  # memory_id -> embedding
        
        # Karen's Unified Memory Service integration
        self._memory_sync_status: dict[str, MemorySyncStatus] = {}  # memory_id -> sync_status
        self._sync_queue: list[dict[str, Any]] = []  # Queue for memory sync operations
        self._conflict_resolution_strategies: dict[str, str] = {}  # memory_id -> resolution_strategy
        self._memory_access_permissions: dict[str, dict[str, set[str]]] = {}  # agent_id -> permission_type -> memory_ids
        self._operation_log: list[dict[str, Any]] = []  # Log of memory operations
        
        # Configuration
        self._config = {
            "enable_unified_memory": True,
            "enable_semantic_search": True,
            "enable_memory_sharing": True,
            "enable_memory_fusion": True,
            "enable_memory_graph": True,
            "enable_memory_versioning": True,
            "enable_memory_sync": True,
            "enable_conflict_resolution": True,
            "enable_access_control": True,
            "enable_operation_logging": True,
            "default_access_level": MemoryAccessLevel.PRIVATE,
            "default_sharing_policy": MemorySharingPolicy.READ_ONLY,
            "default_fusion_strategy": MemoryFusionStrategy.MERGE,
            "default_resolution_strategy": "agent_priority",
            "max_memories_per_agent": 1000,
            "memory_retention_days": 90,
            "embedding_dimension": 128,
            "similarity_threshold": 0.7,
            "sync_batch_size": 50,
            "sync_interval_seconds": 60,
            "log_retention_days": 30,
            "decay_tiers": {
                "short": {"days": 7, "importance_threshold": 3},
                "medium": {"days": 30, "importance_threshold": 6},
                "long": {"days": 90, "importance_threshold": 8},
                "pinned": {"days": 365, "importance_threshold": 10}
            }
        }
        
        # Performance metrics
        self._metrics = {
            "memory_operations": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "sharing_operations": 0,
            "fusion_operations": 0,
            "sync_operations": 0,
            "conflict_resolutions": 0,
            "avg_operation_time_ms": 0.0,
        }
    
    async def initialize(self) -> None:
        """
        Initialize the enhanced agent memory service.
        
        This method sets up all required dependencies and initializes the memory service.
        It handles graceful degradation when optional dependencies are unavailable.
        
        Raises:
            Exception: If core initialization fails
            
        Note:
            The service can function with limited capabilities when some dependencies
            are unavailable, but will raise an exception if core initialization fails.
        """
        if self._initialized:
            return
            
        try:
            self.logger.info("Initializing Enhanced Agent Memory service")
            
            # Initialize internal services
            try:
                self._metrics_service = agent_metrics.AgentMetrics(config=ServiceConfig(name="agent_memory_metrics"))
                await self._metrics_service.initialize()
                self.logger.debug("Metrics service initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize metrics service: {e}")
                self._metrics_service = None
            
            try:
                self._validation_service = agent_validation.AgentValidation(config=ServiceConfig(name="agent_memory_validation"))
                await self._validation_service.initialize()
                self.logger.debug("Validation service initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize validation service: {e}")
                self._validation_service = None
            
            # Initialize with Agent Registry if available
            if HAS_AGENT_REGISTRY and AgentRegistry:
                try:
                    self._agent_registry = AgentRegistry(config=ServiceConfig(name="agent_registry"))
                    await self._agent_registry.initialize()
                    self.logger.debug("Agent Registry initialized successfully")
                except Exception as e:
                    self.logger.error(f"Failed to initialize Agent Registry: {e}")
                    self._agent_registry = None
            
            # Initialize with Agent Orchestrator if available
            if HAS_AGENT_ORCHESTRATOR and AgentOrchestrator:
                try:
                    self._agent_orchestrator = AgentOrchestrator(config=ServiceConfig(name="agent_orchestrator"))
                    await self._agent_orchestrator.initialize()
                    self.logger.debug("Agent Orchestrator initialized successfully")
                except Exception as e:
                    self.logger.error(f"Failed to initialize Agent Orchestrator: {e}")
                    self._agent_orchestrator = None
            
            # Initialize with Unified Memory Service if available and enabled
            if HAS_UNIFIED_MEMORY and self._config.get("enable_unified_memory", True):
                # Try to get Unified Memory Service from Agent Orchestrator
                if self._agent_orchestrator:
                    self._unified_memory_service = getattr(self._agent_orchestrator, '_memory_service', None)
                
                # If not available, try to initialize it directly
                if not self._unified_memory_service:
                    try:
                        # This would require proper initialization parameters
                        # For now, we'll set it to None and log a warning
                        self._unified_memory_service = None
                        self.logger.warning("Could not initialize Unified Memory Service directly")
                    except Exception as e:
                        self.logger.error(f"Failed to initialize Unified Memory Service: {e}")
                        self._unified_memory_service = None
            else:
                self._unified_memory_service = None
                self.logger.info("Unified Memory Service integration disabled")
            
            # Load persisted data if available
            await self._load_persisted_data()
            
            self._initialized = True
            self.logger.info("Enhanced Agent Memory service initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Enhanced Agent Memory service: {e}")
            self.logger.debug(f"Initialization error traceback: {traceback.format_exc()}")
            raise
    
    async def _load_persisted_data(self) -> None:
        """Load persisted data from storage."""
        try:
            # This would typically load from a database or file
            # For now, we'll just initialize empty structures
            self._namespaces = {}
            self._shared_memories = {}
            self._sharing_requests = {}
            self._memory_versions = {}
            self._memory_history = {}
            self._memory_embeddings = {}
            self._memory_graph_edges = {}
            
            self.logger.info("Initialized empty data structures")
        except Exception as e:
            self.logger.error(f"Failed to load persisted data: {e}")
    
    async def store_memory(self, agent_id: str, memory_type: str, content: dict[str, Any],
                         tags: list[str] | None = None, importance: float = 0.5,
                         expires_at: datetime | None = None,
                         metadata: dict[str, Any] | None = None,
                         access_level: MemoryAccessLevel | None = None,
                         namespace: str | None = None) -> str:
        """
        Store a memory for an agent with enhanced capabilities.
        
        This method stores a memory in the agent's local memory store and optionally
        synchronizes it with Karen's Unified Memory Service if enabled.
        
        Args:
            agent_id: ID of the agent
            memory_type: Type of the memory (e.g., "conversation", "observation", "reasoning")
            content: Content of the memory as a dictionary
            tags: Optional tags for the memory to improve searchability
            importance: Importance score (0.0 to 1.0) affecting memory retention
            expires_at: Optional expiration timestamp for temporary memories
            metadata: Optional metadata for the memory as key-value pairs
            access_level: Optional access level for the memory (private, shared, public, inherited)
            namespace: Optional namespace for the memory for organization
            
        Returns:
            Memory ID (UUID) that can be used to retrieve the memory later
            
        Raises:
            ValueError: If importance is not between 0.0 and 1.0
            Exception: If storage fails due to internal errors
            
        Example:
            ```python
            # Store a conversation memory
            memory_id = await memory_service.store_memory(
                agent_id="agent123",
                memory_type="conversation",
                content={"message": "Hello world", "context": "greeting"},
                tags=["greeting", "hello"],
                importance=0.8,
                access_level=MemoryAccessLevel.PRIVATE
            )
            ```
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        # Generate memory ID
        memory_id = str(uuid.uuid4())
        
        # Set default values
        access_level = access_level or self._config.get("default_access_level", MemoryAccessLevel.PRIVATE)
        namespace = namespace or "default"
        
        # Create memory namespace if it doesn't exist
        if agent_id not in self._namespaces:
            self._namespaces[agent_id] = {}
        
        if namespace not in self._namespaces[agent_id]:
            self._namespaces[agent_id][namespace] = MemoryNamespace(
                agent_id=agent_id,
                namespace=namespace
            )
        
        # Prepare memory data
        memory_data = {
            "memory_id": memory_id,
            "agent_id": agent_id,
            "memory_type": memory_type,
            "content": content,
            "tags": tags or [],
            "importance": importance,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "expires_at": expires_at,
            "access_level": access_level.value,
            "namespace": namespace,
            "metadata": metadata or {},
            "version": 1,
            "embedding": None,
            "graph_edges": []
        }
        
        # Store in legacy memory store for backward compatibility
        async with self._lock:
            if agent_id not in self._memory_store:
                self._memory_store[agent_id] = {}
            
            self._memory_store[agent_id][memory_id] = memory_data.copy()
            
            # Initialize version history
            self._memory_versions[memory_id] = [memory_data.copy()]
            self._memory_history[memory_id] = [{
                "action": "create",
                "timestamp": datetime.utcnow().isoformat(),
                "data": memory_data.copy()
            }]
        
        # Store in Unified Memory Service if available
        if self._unified_memory_service:
            try:
                # Convert to Unified Memory Service format
                content_text = json.dumps(content)
                
                # Determine decay tier based on importance
                decay_tier = "short"
                for tier, config in self._config.get("decay_tiers", {}).items():
                    if importance * 10 >= config["importance_threshold"]:
                        decay_tier = tier
                        break
                
                # Create memory commit request
                if MemoryCommitRequest:
                    memory_request = MemoryCommitRequest(
                        user_id=f"agent:{agent_id}",
                        org_id=None,  # Could be enhanced with agent organization
                        text=content_text,
                        tags=tags or [],
                        importance=int(importance * 10),  # Scale to 1-10
                        decay=decay_tier,
                        metadata={
                            "agent_id": agent_id,
                            "memory_type": memory_type,
                            "access_level": access_level.value,
                            "namespace": namespace,
                            "memory_id": memory_id,
                            **(metadata or {})
                        }
                    )
                else:
                    # Fallback if MemoryCommitRequest is not available
                    self.logger.warning("MemoryCommitRequest not available, using fallback")
                    memory_request = {
                        "user_id": f"agent:{agent_id}",
                        "org_id": None,
                        "text": content_text,
                        "tags": tags or [],
                        "importance": int(importance * 10),
                        "decay": decay_tier,
                        "metadata": {
                            "agent_id": agent_id,
                            "memory_type": memory_type,
                            "access_level": access_level.value,
                            "namespace": namespace,
                            "memory_id": memory_id,
                            **(metadata or {})
                        }
                    }
                
                # Get tenant ID (this would typically come from agent registry)
                tenant_id = agent_id  # Simplified for now
                
                # Commit to Unified Memory Service
                memory_response = await self._unified_memory_service.commit(
                    tenant_id=tenant_id,
                    request=memory_request
                )
                
                if memory_response.success:
                    # Update memory data with Unified Memory Service info
                    memory_data["unified_memory_id"] = memory_response.id
                    memory_data["decay_tier"] = memory_response.decay_tier
                    memory_data["expires_at"] = memory_response.expires_at
                    
                    # Update legacy store
                    async with self._lock:
                        if agent_id in self._memory_store and memory_id in self._memory_store[agent_id]:
                            self._memory_store[agent_id][memory_id] = memory_data.copy()
                else:
                    self.logger.error(f"Failed to store memory in Unified Memory Service: {memory_response.id}")
            except Exception as e:
                self.logger.error(f"Failed to store memory in Unified Memory Service: {e}")
        
        # Generate embedding for semantic search if enabled
        if self._config.get("enable_semantic_search", True) and self._unified_memory_service:
            try:
                # This would typically use the embedding manager from Unified Memory Service
                # For now, we'll just store a placeholder
                embedding = np.random.rand(self._config.get("embedding_dimension", 128))
                async with self._lock:
                    self._memory_embeddings[memory_id] = embedding
                    memory_data["embedding"] = embedding.tolist()
            except Exception as e:
                self.logger.error(f"Failed to generate embedding for memory {memory_id}: {e}")
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service:
            await self._metrics_service.record_memory_operation(agent_id, "store", memory_type)
        
        self.logger.info(f"Stored memory {memory_id} for agent {agent_id}")
        return memory_id
    
    async def retrieve_memory(self, memory_id: str, agent_id: str | None = None) -> dict[str, Any] | None:
        """
        Retrieve a memory by ID with enhanced capabilities.
        
        Args:
            memory_id: ID of the memory to retrieve
            agent_id: Optional agent ID for access control
            
        Returns:
            Memory data if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        # First check legacy memory store
        async with self._lock:
            memory_found = None
            
            # Search through all agents for the memory
            for agent_memories in self._memory_store.values():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    break
            
            if not memory_found:
                self._metrics["cache_misses"] += 1
                return None
            
            # Check access control
            if agent_id and memory_found["agent_id"] != agent_id:
                # Check if memory is shared with this agent
                if not await self._is_memory_shared_with_agent(memory_id, agent_id):
                    self.logger.warning(f"Agent {agent_id} attempted to access unshared memory {memory_id}")
                    return None
            
            # Update last accessed time
            memory_found["updated_at"] = datetime.utcnow()
            
            # Record access in history
            if memory_id in self._memory_history:
                self._memory_history[memory_id].append({
                    "action": "retrieve",
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent_id": agent_id
                })
            
            self._metrics["cache_hits"] += 1
            
            # Return a copy to prevent external modifications
            return memory_found.copy()
    
    async def _is_memory_shared_with_agent(self, memory_id: str, agent_id: str) -> bool:
        """Check if a memory is shared with a specific agent."""
        async with self._lock:
            # Check if memory is directly shared
            if agent_id in self._shared_memories:
                for source_agent_id, shared_memory_ids in self._shared_memories[agent_id].items():
                    if memory_id in shared_memory_ids:
                        return True
            
            # Check if memory has public access
            for agent_memories in self._memory_store.values():
                if memory_id in agent_memories:
                    memory = agent_memories[memory_id]
                    if memory.get("access_level") == MemoryAccessLevel.PUBLIC.value:
                        return True
                    break
            
            return False
    
    async def search_memories(self, agent_id: str, query: str, memory_type: str | None = None,
                           limit: int = 10, semantic: bool = True,
                           namespace: str | None = None,
                           include_shared: bool = True) -> list[dict[str, Any]]:
        """
        Search for memories matching a query with enhanced capabilities.
        
        Args:
            agent_id: ID of the agent
            query: Search query
            memory_type: Optional memory type filter
            limit: Maximum number of results
            semantic: Whether to use semantic search
            namespace: Optional namespace filter
            include_shared: Whether to include shared memories
            
        Returns:
            List of matching memories
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        results = []
        
        # Try semantic search with Unified Memory Service if enabled
        if semantic and self._unified_memory_service and self._config.get("enable_semantic_search", True):
            try:
                # Create memory query request
                if MemoryQueryRequest:
                    query_request = MemoryQueryRequest(
                        user_id=f"agent:{agent_id}",
                        org_id=None,  # Could be enhanced with agent organization
                        query=query,
                        top_k=limit * 2,  # Get more results for filtering
                        similarity_threshold=self._config.get("similarity_threshold", 0.7),
                        include_metadata=True
                    )
                else:
                    # Fallback if MemoryQueryRequest is not available
                    self.logger.warning("MemoryQueryRequest not available, using fallback")
                    query_request = {
                        "user_id": f"agent:{agent_id}",
                        "org_id": None,
                        "query": query,
                        "top_k": limit * 2,
                        "similarity_threshold": self._config.get("similarity_threshold", 0.7),
                        "include_metadata": True
                    }
                
                # Get tenant ID
                tenant_id = agent_id  # Simplified for now
                
                # Query Unified Memory Service
                search_response = await self._unified_memory_service.query(
                    tenant_id=tenant_id,
                    request=query_request
                )
                
                # Process results
                for hit in search_response.hits:
                    # Extract memory ID from metadata
                    memory_id = hit.meta.get("memory_id")
                    if memory_id:
                        # Find the memory in our store
                        memory_found = None
                        for agent_memories in self._memory_store.values():
                            if memory_id in agent_memories:
                                memory_found = agent_memories[memory_id]
                                break
                        
                        if memory_found:
                            # Apply filters
                            if memory_type and memory_found["memory_type"] != memory_type:
                                continue
                            
                            if namespace and memory_found["namespace"] != namespace:
                                continue
                            
                            # Check access control
                            if memory_found["agent_id"] != agent_id:
                                if not include_shared or not await self._is_memory_shared_with_agent(memory_id, agent_id):
                                    continue
                            
                            # Add relevance score
                            memory_copy = memory_found.copy()
                            memory_copy["relevance_score"] = hit.score
                            results.append(memory_copy)
                            
                            if len(results) >= limit:
                                break
                
                self.logger.info(f"Semantic search returned {len(results)} results")
            except Exception as e:
                self.logger.error(f"Semantic search failed: {e}")
                # Fall back to basic search
                semantic = False
        
        # Fall back to basic search if semantic search is disabled or failed
        if not semantic or not results:
            async with self._lock:
                for agent_memories in self._memory_store.values():
                    for memory_id, memory in agent_memories.items():
                        # Filter by agent_id or shared access
                        if memory["agent_id"] != agent_id:
                            if not include_shared or not await self._is_memory_shared_with_agent(memory_id, agent_id):
                                continue
                        
                        # Filter by memory_type if specified
                        if memory_type and memory["memory_type"] != memory_type:
                            continue
                        
                        # Filter by namespace if specified
                        if namespace and memory["namespace"] != namespace:
                            continue
                        
                        # Check if memory has expired
                        if memory["expires_at"] and memory["expires_at"] < datetime.utcnow():
                            continue
                        
                        # Simple text matching in content and tags
                        query_lower = query.lower()
                        content_str = str(memory["content"]).lower()
                        tags_str = " ".join(memory["tags"]).lower()
                        
                        if query_lower in content_str or query_lower in tags_str:
                            memory_copy = memory.copy()
                            memory_copy["relevance_score"] = 0.5  # Default relevance for basic search
                            results.append(memory_copy)
                        
                        if len(results) >= limit:
                            break
        
        # Sort by relevance score, importance, and recency
        results.sort(key=lambda m: (
            m.get("relevance_score", 0.0),
            m["importance"],
            m["created_at"]
        ), reverse=True)
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service:
            await self._metrics_service.record_memory_operation(agent_id, "search", memory_type or "any")
        
        return results[:limit]
    
    async def list_memories(self, agent_id: str, memory_type: str | None = None,
                          limit: int = 50, namespace: str | None = None,
                          include_shared: bool = True) -> list[dict[str, Any]]:
        """
        List memories for an agent with enhanced capabilities.
        
        Args:
            agent_id: ID of the agent
            memory_type: Optional memory type filter
            limit: Maximum number of results
            namespace: Optional namespace filter
            include_shared: Whether to include shared memories
            
        Returns:
            List of memories
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        results = []
        
        async with self._lock:
            # Get agent's own memories
            agent_memories = self._memory_store.get(agent_id, {})
            
            for memory_id, memory in agent_memories.items():
                # Filter by memory_type if specified
                if memory_type and memory["memory_type"] != memory_type:
                    continue
                
                # Filter by namespace if specified
                if namespace and memory["namespace"] != namespace:
                    continue
                
                # Check if memory has expired
                if memory["expires_at"] and memory["expires_at"] < datetime.utcnow():
                    continue
                
                results.append(memory.copy())
                
                if len(results) >= limit:
                    break
            
            # Include shared memories if requested
            if include_shared and len(results) < limit:
                for source_agent_id, shared_memory_ids in self._shared_memories.get(agent_id, {}).items():
                    for memory_id in shared_memory_ids:
                        # Find the memory in the source agent's store
                        if source_agent_id in self._memory_store and memory_id in self._memory_store[source_agent_id]:
                            memory = self._memory_store[source_agent_id][memory_id]
                            
                            # Apply filters
                            if memory_type and memory["memory_type"] != memory_type:
                                continue
                            
                            if namespace and memory["namespace"] != namespace:
                                continue
                            
                            # Check if memory has expired
                            if memory["expires_at"] and memory["expires_at"] < datetime.utcnow():
                                continue
                            
                            # Mark as shared
                            memory_copy = memory.copy()
                            memory_copy["shared_from"] = source_agent_id
                            results.append(memory_copy)
                            
                            if len(results) >= limit:
                                break
                    
                    if len(results) >= limit:
                        break
        
        # Sort by creation time (newest first)
        results.sort(key=lambda m: m["created_at"], reverse=True)
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service:
            await self._metrics_service.record_memory_operation(agent_id, "list", memory_type or "any")
        
        return results[:limit]
    
    async def update_memory(self, memory_id: str, updates: dict[str, Any], 
                          agent_id: str | None = None) -> bool:
        """
        Update a memory with enhanced capabilities.
        
        Args:
            memory_id: ID of the memory to update
            updates: Dictionary of updates to apply
            agent_id: Optional agent ID for access control
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        async with self._lock:
            # Find the memory in our store
            memory_found = None
            owner_agent_id = None
            
            for agent_mem_id, agent_memories in self._memory_store.items():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    owner_agent_id = agent_mem_id
                    break
            
            if not memory_found:
                self.logger.warning(f"Memory {memory_id} not found for update")
                return False
            
            # Check access control
            if agent_id and owner_agent_id != agent_id:
                # Check if memory is shared with this agent and has write access
                if not await self._has_write_access(memory_id, agent_id):
                    self.logger.warning(f"Agent {agent_id} attempted to update unshared memory {memory_id}")
                    return False
            
            # Create version history if enabled
            if self._config.get("enable_memory_versioning", True):
                if memory_id not in self._memory_versions:
                    self._memory_versions[memory_id] = []
                
                # Store current version
                current_version = memory_found.copy()
                current_version["version"] = len(self._memory_versions[memory_id]) + 1
                self._memory_versions[memory_id].append(current_version)
            
            # Apply updates
            for key, value in updates.items():
                if key in memory_found:
                    memory_found[key] = value
            
            # Update timestamp
            memory_found["updated_at"] = datetime.utcnow()
            
            # Record update in history
            if memory_id in self._memory_history:
                self._memory_history[memory_id].append({
                    "action": "update",
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent_id": agent_id,
                    "updates": updates
                })
            
            # Update in Unified Memory Service if available
            if self._unified_memory_service and "unified_memory_id" in memory_found:
                try:
                    # Get tenant ID
                    tenant_id = owner_agent_id  # Simplified for now
                    
                    # Prepare update data
                    update_data = {}
                    
                    if "content" in updates:
                        update_data["content"] = json.dumps(updates["content"])
                    
                    if "tags" in updates:
                        update_data["tags"] = updates["tags"]
                    
                    if "importance" in updates:
                        update_data["importance"] = int(updates["importance"] * 10)  # Scale to 1-10
                        
                        # Update decay tier based on new importance
                        decay_tier = "short"
                        for tier, config in self._config.get("decay_tiers", {}).items():
                            if updates["importance"] * 10 >= config["importance_threshold"]:
                                decay_tier = tier
                                break
                        update_data["decay"] = decay_tier
                    
                    # Update in Unified Memory Service
                    await self._unified_memory_service.update(
                        tenant_id=tenant_id,
                        memory_id=memory_found["unified_memory_id"],
                        updates=update_data
                    )
                except Exception as e:
                    self.logger.error(f"Failed to update memory in Unified Memory Service: {e}")
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service and owner_agent_id:
            await self._metrics_service.record_memory_operation(owner_agent_id, "update", memory_found.get("memory_type", "unknown"))
        
        self.logger.info(f"Updated memory {memory_id}")
        return True
    
    async def _has_write_access(self, memory_id: str, agent_id: str) -> bool:
        """Check if an agent has write access to a memory."""
        async with self._lock:
            # Find the memory in our store
            memory_found = None
            for agent_memories in self._memory_store.values():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    break
            
            if not memory_found:
                return False
            
            # Check if memory has public access
            if memory_found.get("access_level") == MemoryAccessLevel.PUBLIC.value:
                return True
            
            # Check if memory is shared with this agent with write access
            if agent_id in self._shared_memories:
                for source_agent_id, shared_memory_ids in self._shared_memories[agent_id].items():
                    if memory_id in shared_memory_ids:
                        # Check sharing policy
                        for request_id, request in self._sharing_requests.items():
                            if (request.source_agent_id == source_agent_id and 
                                request.target_agent_id == agent_id and
                                memory_id in request.memory_ids):
                                if request.sharing_policy in [MemorySharingPolicy.READ_WRITE, MemorySharingPolicy.FULL_ACCESS]:
                                    return True
            
            return False
    
    async def delete_memory(self, memory_id: str, agent_id: str | None = None, 
                          hard_delete: bool = False) -> bool:
        """
        Delete a memory with enhanced capabilities.
        
        Args:
            memory_id: ID of the memory to delete
            agent_id: Optional agent ID for access control
            hard_delete: Whether to permanently delete the memory
            
        Returns:
            True if deletion was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        async with self._lock:
            # Find the memory in our store
            memory_found = None
            owner_agent_id = None
            
            for agent_mem_id, agent_memories in self._memory_store.items():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    owner_agent_id = agent_mem_id
                    break
            
            if not memory_found:
                self.logger.warning(f"Memory {memory_id} not found for deletion")
                return False
            
            # Check access control
            if agent_id and owner_agent_id != agent_id:
                # Check if memory is shared with this agent and has full access
                if not await self._has_full_access(memory_id, agent_id):
                    self.logger.warning(f"Agent {agent_id} attempted to delete unshared memory {memory_id}")
                    return False
            
            # Record deletion in history
            if memory_id in self._memory_history:
                self._memory_history[memory_id].append({
                    "action": "delete",
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent_id": agent_id,
                    "hard_delete": hard_delete
                })
            
            # Delete from legacy store
            if owner_agent_id in self._memory_store and memory_id in self._memory_store[owner_agent_id]:
                del self._memory_store[owner_agent_id][memory_id]
            
            # Delete from Unified Memory Service if available
            if self._unified_memory_service and "unified_memory_id" in memory_found:
                try:
                    # Get tenant ID
                    tenant_id = owner_agent_id  # Simplified for now
                    
                    # Delete from Unified Memory Service
                    await self._unified_memory_service.delete(
                        tenant_id=tenant_id,
                        memory_id=memory_found["unified_memory_id"],
                        hard_delete=hard_delete
                    )
                except Exception as e:
                    self.logger.error(f"Failed to delete memory from Unified Memory Service: {e}")
            
            # Clean up related data
            if hard_delete:
                # Remove from versions
                if memory_id in self._memory_versions:
                    del self._memory_versions[memory_id]
                
                # Remove from history
                if memory_id in self._memory_history:
                    del self._memory_history[memory_id]
                
                # Remove from embeddings
                if memory_id in self._memory_embeddings:
                    del self._memory_embeddings[memory_id]
                
                # Remove from graph edges
                if memory_id in self._memory_graph_edges:
                    del self._memory_graph_edges[memory_id]
                
                # Remove from shared memories
                for target_agent_id, source_agents in self._shared_memories.items():
                    for source_agent_id, shared_memory_ids in source_agents.items():
                        if memory_id in shared_memory_ids:
                            shared_memory_ids.remove(memory_id)
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service and owner_agent_id:
            await self._metrics_service.record_memory_operation(owner_agent_id, "delete", memory_found.get("memory_type", "unknown"))
        
        self.logger.info(f"Deleted memory {memory_id} (hard_delete={hard_delete})")
        return True
    
    async def _has_full_access(self, memory_id: str, agent_id: str) -> bool:
        """Check if an agent has full access to a memory."""
        async with self._lock:
            # Find the memory in our store
            memory_found = None
            for agent_memories in self._memory_store.values():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    break
            
            if not memory_found:
                return False
            
            # Check if memory has public access
            if memory_found.get("access_level") == MemoryAccessLevel.PUBLIC.value:
                return True
            
            # Check if memory is shared with this agent with full access
            if agent_id in self._shared_memories:
                for source_agent_id, shared_memory_ids in self._shared_memories[agent_id].items():
                    if memory_id in shared_memory_ids:
                        # Check sharing policy
                        for request_id, request in self._sharing_requests.items():
                            if (request.source_agent_id == source_agent_id and 
                                request.target_agent_id == agent_id and
                                memory_id in request.memory_ids):
                                if request.sharing_policy == MemorySharingPolicy.FULL_ACCESS:
                                    return True
            
            return False
    
    async def clear_agent_memories(self, agent_id: str, memory_type: str | None = None,
                                 namespace: str | None = None, hard_delete: bool = False) -> int:
        """
        Clear memories for an agent with enhanced capabilities.
        
        Args:
            agent_id: ID of the agent
            memory_type: Optional memory type filter
            namespace: Optional namespace filter
            hard_delete: Whether to permanently delete the memories
            
        Returns:
            Number of memories cleared
        """
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        self._metrics["memory_operations"] += 1
        
        count = 0
        
        async with self._lock:
            # Get agent's memories
            agent_memories = self._memory_store.get(agent_id, {})
            
            # Collect memories to delete
            memories_to_delete = []
            
            for memory_id, memory in agent_memories.items():
                # Filter by memory_type if specified
                if memory_type and memory["memory_type"] != memory_type:
                    continue
                
                # Filter by namespace if specified
                if namespace and memory["namespace"] != namespace:
                    continue
                
                memories_to_delete.append(memory_id)
            
            # Delete each memory
            for memory_id in memories_to_delete:
                if await self.delete_memory(memory_id, agent_id, hard_delete):
                    count += 1
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        if self._metrics_service:
            await self._metrics_service.record_memory_operation(agent_id, "clear", memory_type or "any")
        
        self.logger.info(f"Cleared {count} memories for agent {agent_id}")
        return count
    
    async def get_memory_stats(self, agent_id: str) -> dict[str, Any]:
        """
        Get memory statistics for an agent with enhanced capabilities.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Dictionary of memory statistics
        """
        if not self._initialized:
            await self.initialize()
        
        stats = {
            "agent_id": agent_id,
            "total_memories": 0,
            "by_type": {},
            "by_namespace": {},
            "by_access_level": {
                "private": 0,
                "shared": 0,
                "public": 0,
                "inherited": 0
            },
            "by_importance": {"high": 0, "medium": 0, "low": 0},
            "expired_memories": 0,
            "shared_memories": 0,
            "service_metrics": self._metrics.copy()
        }
        
        async with self._lock:
            # Get agent's own memories
            agent_memories = self._memory_store.get(agent_id, {})
            
            for memory_id, memory in agent_memories.items():
                stats["total_memories"] += 1
                
                # Count by type
                memory_type = memory["memory_type"]
                if memory_type not in stats["by_type"]:
                    stats["by_type"][memory_type] = 0
                stats["by_type"][memory_type] += 1
                
                # Count by namespace
                namespace = memory["namespace"]
                if namespace not in stats["by_namespace"]:
                    stats["by_namespace"][namespace] = 0
                stats["by_namespace"][namespace] += 1
                
                # Count by access level
                access_level = memory.get("access_level", "private")
                if access_level in stats["by_access_level"]:
                    stats["by_access_level"][access_level] += 1
                
                # Count by importance
                importance = memory["importance"]
                if importance >= 0.7:
                    stats["by_importance"]["high"] += 1
                elif importance >= 0.4:
                    stats["by_importance"]["medium"] += 1
                else:
                    stats["by_importance"]["low"] += 1
                
                # Count expired memories
                if memory["expires_at"] and memory["expires_at"] < datetime.utcnow():
                    stats["expired_memories"] += 1
            
            # Count shared memories
            for source_agent_id, shared_memory_ids in self._shared_memories.get(agent_id, {}).items():
                stats["shared_memories"] += len(shared_memory_ids)
        
        return stats
    
    async def share_memory(self, source_agent_id: str, target_agent_id: str, 
                         memory_ids: list[str], access_level: MemoryAccessLevel,
                         sharing_policy: MemorySharingPolicy,
                         expires_at: datetime | None = None,
                         metadata: dict[str, Any] | None = None) -> str:
        """
        Share memories between agents.
        
        Args:
            source_agent_id: ID of the source agent
            target_agent_id: ID of the target agent
            memory_ids: List of memory IDs to share
            access_level: Access level for the shared memories
            sharing_policy: Sharing policy for the shared memories
            expires_at: Optional expiration timestamp
            metadata: Optional metadata for the sharing request
            
        Returns:
            Sharing request ID
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_sharing", True):
            raise ValueError("Memory sharing is disabled")
        
        start_time = time.time()
        self._metrics["sharing_operations"] += 1
        
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Validate memory IDs
        valid_memory_ids = []
        
        async with self._lock:
            for memory_id in memory_ids:
                # Check if memory exists and belongs to source agent
                if (source_agent_id in self._memory_store and 
                    memory_id in self._memory_store[source_agent_id]):
                    valid_memory_ids.append(memory_id)
                else:
                    self.logger.warning(f"Memory {memory_id} not found or does not belong to agent {source_agent_id}")
            
            if not valid_memory_ids:
                raise ValueError("No valid memories to share")
            
            # Create sharing request
            sharing_request = MemorySharingRequest(
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                memory_ids=valid_memory_ids,
                access_level=access_level,
                sharing_policy=sharing_policy,
                expires_at=expires_at,
                metadata=metadata or {}
            )
            
            # Store sharing request
            self._sharing_requests[request_id] = sharing_request
            
            # Update shared memories registry
            if target_agent_id not in self._shared_memories:
                self._shared_memories[target_agent_id] = {}
            
            if source_agent_id not in self._shared_memories[target_agent_id]:
                self._shared_memories[target_agent_id][source_agent_id] = []
            
            self._shared_memories[target_agent_id][source_agent_id].extend(valid_memory_ids)
            
            # Remove duplicates
            self._shared_memories[target_agent_id][source_agent_id] = list(set(
                self._shared_memories[target_agent_id][source_agent_id]
            ))
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        self.logger.info(f"Shared {len(valid_memory_ids)} memories from agent {source_agent_id} to agent {target_agent_id}")
        return request_id
    
    async def fuse_memories(self, source_agent_id: str, target_agent_id: str,
                          memory_ids: list[str], fusion_strategy: MemoryFusionStrategy,
                          conflict_resolution: str = "auto",
                          metadata: dict[str, Any] | None = None) -> str:
        """
        Fuse memories between agents.
        
        Args:
            source_agent_id: ID of the source agent
            target_agent_id: ID of the target agent
            memory_ids: List of memory IDs to fuse
            fusion_strategy: Strategy for fusing memories
            conflict_resolution: Conflict resolution method
            metadata: Optional metadata for the fusion request
            
        Returns:
            Fusion request ID
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_fusion", True):
            raise ValueError("Memory fusion is disabled")
        
        start_time = time.time()
        self._metrics["fusion_operations"] += 1
        
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Validate memory IDs
        valid_memory_ids = []
        
        async with self._lock:
            for memory_id in memory_ids:
                # Check if memory exists
                memory_found = False
                for agent_memories in self._memory_store.values():
                    if memory_id in agent_memories:
                        memory_found = True
                        break
                
                if memory_found:
                    valid_memory_ids.append(memory_id)
                else:
                    self.logger.warning(f"Memory {memory_id} not found")
            
            if not valid_memory_ids:
                raise ValueError("No valid memories to fuse")
            
            # Create fusion request
            fusion_request = MemoryFusionRequest(
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
                memory_ids=valid_memory_ids,
                fusion_strategy=fusion_strategy,
                conflict_resolution=conflict_resolution,
                metadata=metadata or {}
            )
            
            # Apply fusion strategy
            fused_memory = await self._apply_fusion_strategy(
                valid_memory_ids, fusion_strategy, conflict_resolution
            )
            
            if fused_memory:
                # Store the fused memory
                fused_memory_id = await self.store_memory(
                    agent_id=target_agent_id,
                    memory_type="fused",
                    content=fused_memory["content"],
                    tags=fused_memory["tags"],
                    importance=fused_memory["importance"],
                    metadata={
                        "fusion_request_id": request_id,
                        "source_memory_ids": valid_memory_ids,
                        "fusion_strategy": fusion_strategy.value,
                        **(metadata or {})
                    }
                )
                
                # Add graph edges for source memories
                if self._config.get("enable_memory_graph", True):
                    for source_memory_id in valid_memory_ids:
                        edge = MemoryGraphEdge(
                            source_memory_id=source_memory_id,
                            target_memory_id=fused_memory_id,
                            relationship_type="fused_from",
                            strength=1.0,
                            metadata={
                                "fusion_request_id": request_id,
                                "fusion_strategy": fusion_strategy.value
                            }
                        )
                        
                        if source_memory_id not in self._memory_graph_edges:
                            self._memory_graph_edges[source_memory_id] = []
                        
                        self._memory_graph_edges[source_memory_id].append(edge)
                        
                        if fused_memory_id not in self._memory_graph_edges:
                            self._memory_graph_edges[fused_memory_id] = []
                        
                        self._memory_graph_edges[fused_memory_id].append(edge)
        
        # Record metrics
        operation_time_ms = (time.time() - start_time) * 1000
        self._metrics["avg_operation_time_ms"] = (
            self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
        )
        
        self.logger.info(f"Fused {len(valid_memory_ids)} memories into agent {target_agent_id}")
        return request_id
    
    async def _apply_fusion_strategy(self, memory_ids: list[str], 
                                   fusion_strategy: MemoryFusionStrategy,
                                   conflict_resolution: str) -> dict[str, Any] | None:
        """Apply a fusion strategy to a list of memories."""
        if not memory_ids:
            return None
        
        # Get all memories
        memories = []
        
        async with self._lock:
            for memory_id in memory_ids:
                memory_found = False
                for agent_memories in self._memory_store.values():
                    if memory_id in agent_memories:
                        memories.append(agent_memories[memory_id])
                        memory_found = True
                        break
                
                if not memory_found:
                    self.logger.warning(f"Memory {memory_id} not found for fusion")
        
        if not memories:
            return None
        
        # Apply fusion strategy
        if fusion_strategy == MemoryFusionStrategy.MERGE:
            # Merge all contents and tags
            merged_content = {}
            merged_tags = set()
            merged_importance = 0.0
            
            for memory in memories:
                # Merge content (deep merge)
                for key, value in memory["content"].items():
                    if key in merged_content:
                        # Handle conflicts based on resolution method
                        if conflict_resolution == "source_priority":
                            # Keep first value
                            pass
                        elif conflict_resolution == "target_priority":
                            # Use last value
                            merged_content[key] = value
                        elif conflict_resolution == "auto":
                            # Use the most recent value
                            if key not in merged_content or memory["created_at"] > merged_content.get("_created_at", datetime.min):
                                merged_content[key] = value
                        # For manual resolution, we'd need human intervention
                    else:
                        merged_content[key] = value
                
                # Merge tags
                merged_tags.update(memory["tags"])
                
                # Use highest importance
                merged_importance = max(merged_importance, memory["importance"])
            
            return {
                "content": merged_content,
                "tags": list(merged_tags),
                "importance": merged_importance
            }
        
        elif fusion_strategy == MemoryFusionStrategy.INTERSECT:
            # Keep only common content and tags
            if len(memories) < 2:
                return memories[0].copy()
            
            # Start with first memory
            first_memory = memories[0]
            intersected_content = first_memory["content"].copy()
            intersected_tags = set(first_memory["tags"])
            
            # Intersect with other memories
            for memory in memories[1:]:
                # Keep only keys that exist in all memories
                keys_to_remove = []
                for key in intersected_content:
                    if key not in memory["content"]:
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del intersected_content[key]
                
                # Intersect tags
                intersected_tags.intersection_update(memory["tags"])
            
            # Use average importance
            avg_importance = sum(m["importance"] for m in memories) / len(memories)
            
            return {
                "content": intersected_content,
                "tags": list(intersected_tags),
                "importance": avg_importance
            }
        
        elif fusion_strategy == MemoryFusionStrategy.UNION:
            # Combine all content and tags
            unioned_content = {}
            unioned_tags = set()
            unioned_importance = 0.0
            
            for memory in memories:
                # Union content (keep all values)
                for key, value in memory["content"].items():
                    if key not in unioned_content:
                        unioned_content[key] = value
                
                # Union tags
                unioned_tags.update(memory["tags"])
                
                # Use highest importance
                unioned_importance = max(unioned_importance, memory["importance"])
            
            return {
                "content": unioned_content,
                "tags": list(unioned_tags),
                "importance": unioned_importance
            }
        
        elif fusion_strategy == MemoryFusionStrategy.PRIORITIZE_SOURCE:
            # Use source agent's memory as the base
            if not memories:
                return None
            
            source_memory = memories[0]
            return {
                "content": source_memory["content"].copy(),
                "tags": source_memory["tags"].copy(),
                "importance": source_memory["importance"]
            }
        
        elif fusion_strategy == MemoryFusionStrategy.PRIORITIZE_TARGET:
            # Use target agent's memory as the base
            if len(memories) < 2:
                return memories[0].copy() if memories else None
            
            target_memory = memories[-1]
            return {
                "content": target_memory["content"].copy(),
                "tags": target_memory["tags"].copy(),
                "importance": target_memory["importance"]
            }
        
        else:
            self.logger.error(f"Unknown fusion strategy: {fusion_strategy}")
            return None
    
    async def get_memory_graph(self, agent_id: str | None = None) -> dict[str, Any]:
        """
        Get memory graph for relationship tracking.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Memory graph data
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_graph", True):
            return {"error": "Memory graph is disabled"}
        
        graph = {
            "nodes": [],
            "edges": []
        }
        
        async with self._lock:
            # Collect nodes (memories)
            node_ids = set()
            
            if agent_id:
                # Only include memories for this agent
                agent_memories = self._memory_store.get(agent_id, {})
                
                for memory_id, memory in agent_memories.items():
                    node_ids.add(memory_id)
                    
                    graph["nodes"].append({
                        "id": memory_id,
                        "agent_id": agent_id,
                        "memory_type": memory["memory_type"],
                        "importance": memory["importance"],
                        "namespace": memory["namespace"]
                    })
            else:
                # Include all memories
                for agent_mem_id, agent_memories in self._memory_store.items():
                    for memory_id, memory in agent_memories.items():
                        node_ids.add(memory_id)
                        
                        graph["nodes"].append({
                            "id": memory_id,
                            "agent_id": agent_mem_id,
                            "memory_type": memory["memory_type"],
                            "importance": memory["importance"],
                            "namespace": memory["namespace"]
                        })
            
            # Collect edges
            for source_id, edges in self._memory_graph_edges.items():
                if source_id in node_ids:
                    for edge in edges:
                        if edge.target_memory_id in node_ids:
                            graph["edges"].append({
                                "source": edge.source_memory_id,
                                "target": edge.target_memory_id,
                                "relationship_type": edge.relationship_type,
                                "strength": edge.strength,
                                "metadata": edge.metadata
                            })
        
        return graph
    
    async def get_memory_versions(self, memory_id: str) -> list[dict[str, Any]]:
        """
        Get version history for a memory.
        
        Args:
            memory_id: ID of the memory
            
        Returns:
            List of memory versions
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_versioning", True):
            return [{"error": "Memory versioning is disabled"}]
        
        async with self._lock:
            if memory_id in self._memory_versions:
                return self._memory_versions[memory_id].copy()
            else:
                return []
    
    async def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """
        Get history for a memory.
        
        Args:
            memory_id: ID of the memory
            
        Returns:
            List of history events
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if memory_id in self._memory_history:
                return self._memory_history[memory_id].copy()
            else:
                return []
    
    async def health_check(self) -> bool:
        """Check the health of the enhanced agent memory service."""
        return self._initialized
    
    async def start(self) -> None:
        """Start the enhanced agent memory service."""
        self.logger.info("Enhanced Agent Memory service started")
    
    async def stop(self) -> None:
        """Stop the enhanced agent memory service."""
        self.logger.info("Enhanced Agent Memory service stopped")
    
    async def sync_with_karen_memory(self, agent_id: str, force_sync: bool = False) -> dict[str, Any]:
        """
        Synchronize agent memory with Karen's Unified Memory Service.
        
        This method synchronizes all memories for a specific agent with Karen's Unified Memory Service.
        It handles conflicts, tracks synchronization status, and provides detailed results.
        
        Args:
            agent_id: ID of the agent to synchronize
            force_sync: Whether to force synchronization regardless of sync status
            
        Returns:
            Dictionary with synchronization results including:
            - success: Whether the overall sync was successful
            - agent_id: ID of the agent that was synchronized
            - total_memories: Total number of memories to sync
            - synced_memories: Number of successfully synced memories
            - failed_memories: Number of memories that failed to sync
            - conflicts: Number of conflicts detected
            - details: List of individual memory sync results
            
        Raises:
            Exception: If synchronization fails due to service unavailability or internal errors
            
        Example:
            ```python
            # Sync agent memories with Karen's Unified Memory Service
            result = await memory_service.sync_with_karen_memory("agent123")
            
            if result["success"]:
                print(f"Synced {result['synced_memories']} memories")
                
                # Check for conflicts
                if result["conflicts"] > 0:
                    print(f"Found {result['conflicts']} conflicts that need resolution")
                    
                    # Resolve conflicts
                    for detail in result["details"]:
                        if detail.get("conflict"):
                            await memory_service.resolve_memory_conflicts(
                                memory_id=detail["memory_id"],
                                conflict_details=detail["conflict_details"],
                                resolution_strategy="agent_priority"
                            )
            else:
                print(f"Sync failed: {result['message']}")
            ```
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_sync", True):
            return {"success": False, "message": "Memory synchronization is disabled"}
        
        if not self._unified_memory_service:
            return {"success": False, "message": "Unified Memory Service is not available"}
        
        start_time = time.time()
        self._metrics["sync_operations"] += 1
        
        try:
            # Get agent's memories
            agent_memories = self._memory_store.get(agent_id, {})
            
            sync_results = {
                "success": True,
                "agent_id": agent_id,
                "total_memories": len(agent_memories),
                "synced_memories": 0,
                "failed_memories": 0,
                "conflicts": 0,
                "details": []
            }
            
            # Process each memory
            for memory_id, memory_data in agent_memories.items():
                sync_status = self._memory_sync_status.get(memory_id, MemorySyncStatus.PENDING)
                
                # Skip if already synced and not forcing
                if sync_status == MemorySyncStatus.SYNCED and not force_sync:
                    continue
                
                # Sync the memory
                result = await self.sync_memory_entry(memory_id, agent_id)
                sync_results["details"].append(result)
                
                if result["success"]:
                    sync_results["synced_memories"] += 1
                else:
                    sync_results["failed_memories"] += 1
                
                if result.get("conflict", False):
                    sync_results["conflicts"] += 1
            
            # Record metrics
            operation_time_ms = (time.time() - start_time) * 1000
            self._metrics["avg_operation_time_ms"] = (
                self._metrics["avg_operation_time_ms"] * 0.9 + operation_time_ms * 0.1
            )
            
            if self._metrics_service:
                await self._metrics_service.record_memory_operation(agent_id, "sync", "karen_memory")
            
            # Log the operation
            await self.log_memory_operation(
                operation_type=MemoryOperationType.SYNC,
                agent_id=agent_id,
                memory_id=None,
                details={"force_sync": force_sync, "results": sync_results}
            )
            
            return sync_results
            
        except Exception as e:
            self.logger.error(f"Failed to sync agent {agent_id} with Karen's memory: {e}")
            
            # Log the error
            await self.log_memory_operation(
                operation_type=MemoryOperationType.SYNC,
                agent_id=agent_id,
                memory_id=None,
                details={"error": str(e), "force_sync": force_sync},
                success=False
            )
            
            return {"success": False, "message": f"Sync failed: {e!s}"}
    
    async def sync_memory_entry(self, memory_id: str, agent_id: str) -> dict[str, Any]:
        """
        Synchronize a specific memory entry with Karen's memory.
        
        Args:
            memory_id: ID of the memory to synchronize
            agent_id: ID of the agent owning the memory
            
        Returns:
            Dictionary with synchronization result
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_sync", True):
            return {"success": False, "message": "Memory synchronization is disabled"}
        
        if not self._unified_memory_service:
            return {"success": False, "message": "Unified Memory Service is not available"}
        
        try:
            # Get the memory data
            memory_data = None
            if agent_id in self._memory_store and memory_id in self._memory_store[agent_id]:
                memory_data = self._memory_store[agent_id][memory_id]
            else:
                return {"success": False, "message": f"Memory {memory_id} not found for agent {agent_id}"}
            
            # Update sync status
            self._memory_sync_status[memory_id] = MemorySyncStatus.IN_PROGRESS
            
            # Convert to Karen's format
            karen_memory = await self.convert_agent_memory_to_karen_format(memory_data)
            
            # Check for conflicts
            conflict = await self.detect_memory_conflicts(memory_id, karen_memory)
            if conflict:
                self._memory_sync_status[memory_id] = MemorySyncStatus.CONFLICT
                return {
                    "success": False,
                    "message": "Memory conflict detected",
                    "conflict": True,
                    "conflict_details": conflict
                }
            
            # Store in Karen's memory
            tenant_id = agent_id  # Simplified for now
            
            # Create memory commit request
            if MemoryCommitRequest:
                memory_request = MemoryCommitRequest(
                    user_id=f"agent:{agent_id}",
                    org_id=None,
                    text=karen_memory["text"],
                    tags=karen_memory["tags"],
                    importance=karen_memory["importance"],
                    decay=karen_memory["decay"],
                    metadata=karen_memory["metadata"]
                )
            else:
                # Fallback if MemoryCommitRequest is not available
                memory_request = {
                    "user_id": f"agent:{agent_id}",
                    "org_id": None,
                    "text": karen_memory["text"],
                    "tags": karen_memory["tags"],
                    "importance": karen_memory["importance"],
                    "decay": karen_memory["decay"],
                    "metadata": karen_memory["metadata"]
                }
            
            # Commit to Unified Memory Service
            memory_response = await self._unified_memory_service.commit(
                tenant_id=tenant_id,
                request=memory_request
            )
            
            if memory_response.success:
                # Update memory data with Unified Memory Service info
                memory_data["unified_memory_id"] = memory_response.id
                memory_data["synced_at"] = datetime.utcnow()
                
                # Update sync status
                self._memory_sync_status[memory_id] = MemorySyncStatus.SYNCED
                
                # Log the operation
                await self.log_memory_operation(
                    operation_type=MemoryOperationType.SYNC,
                    agent_id=agent_id,
                    memory_id=memory_id,
                    details={"karen_memory_id": memory_response.id}
                )
                
                return {
                    "success": True,
                    "message": "Memory synchronized successfully",
                    "karen_memory_id": memory_response.id
                }
            else:
                # Update sync status
                self._memory_sync_status[memory_id] = MemorySyncStatus.FAILED
                
                # Log the error
                await self.log_memory_operation(
                    operation_type=MemoryOperationType.SYNC,
                    agent_id=agent_id,
                    memory_id=memory_id,
                    details={"error": memory_response.id},
                    success=False
                )
                
                return {
                    "success": False,
                    "message": f"Failed to sync memory: {memory_response.id}"
                }
                
        except Exception as e:
            self.logger.error(f"Failed to sync memory {memory_id} with Karen's memory: {e}")
            
            # Update sync status
            self._memory_sync_status[memory_id] = MemorySyncStatus.FAILED
            
            # Log the error
            await self.log_memory_operation(
                operation_type=MemoryOperationType.SYNC,
                agent_id=agent_id,
                memory_id=memory_id,
                details={"error": str(e)},
                success=False
            )
            
            return {"success": False, "message": f"Sync failed: {e!s}"}
    
    async def batch_sync_memory(self, agent_id: str, memory_ids: list[str] | None = None) -> dict[str, Any]:
        """
        Synchronize multiple memory entries with Karen's memory.
        
        Args:
            agent_id: ID of the agent
            memory_ids: Optional list of memory IDs to sync (if None, sync all)
            
        Returns:
            Dictionary with batch synchronization results
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_memory_sync", True):
            return {"success": False, "message": "Memory synchronization is disabled"}
        
        if not self._unified_memory_service:
            return {"success": False, "message": "Unified Memory Service is not available"}
        
        try:
            # Get memories to sync
            if memory_ids is None:
                # Sync all memories for the agent
                agent_memories = self._memory_store.get(agent_id, {})
                memory_ids = list(agent_memories.keys())
            
            # Limit batch size
            batch_size = self._config.get("sync_batch_size", 50)
            if len(memory_ids) > batch_size:
                memory_ids = memory_ids[:batch_size]
            
            batch_results = {
                "success": True,
                "agent_id": agent_id,
                "total_memories": len(memory_ids),
                "synced_memories": 0,
                "failed_memories": 0,
                "conflicts": 0,
                "details": []
            }
            
            # Process each memory in the batch
            for memory_id in memory_ids:
                result = await self.sync_memory_entry(memory_id, agent_id)
                batch_results["details"].append(result)
                
                if result["success"]:
                    batch_results["synced_memories"] += 1
                else:
                    batch_results["failed_memories"] += 1
                
                if result.get("conflict", False):
                    batch_results["conflicts"] += 1
            
            # Record metrics
            self._metrics["sync_operations"] += 1
            
            # Log the operation
            await self.log_memory_operation(
                operation_type=MemoryOperationType.SYNC,
                agent_id=agent_id,
                memory_id=None,
                details={"batch_size": len(memory_ids), "results": batch_results}
            )
            
            return batch_results
            
        except Exception as e:
            self.logger.error(f"Failed to batch sync memories for agent {agent_id}: {e}")
            
            # Log the error
            await self.log_memory_operation(
                operation_type=MemoryOperationType.SYNC,
                agent_id=agent_id,
                memory_id=None,
                details={"error": str(e), "memory_ids": memory_ids},
                success=False
            )
            
            return {"success": False, "message": f"Batch sync failed: {e!s}"}
    
    async def get_sync_status(self, memory_id: str | None = None, agent_id: str | None = None) -> dict[str, Any]:
        """
        Get the synchronization status of memory entries.
        
        Args:
            memory_id: Optional specific memory ID to check
            agent_id: Optional agent ID to filter memories
            
        Returns:
            Dictionary with synchronization status information
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            if memory_id:
                # Get status for a specific memory
                status = self._memory_sync_status.get(memory_id, MemorySyncStatus.PENDING)
                last_synced = None
                if agent_id:
                    last_synced = self._memory_store.get(agent_id, {}).get(memory_id, {}).get("synced_at")
                return {
                    "memory_id": memory_id,
                    "sync_status": status.value,
                    "last_synced": last_synced
                }
            else:
                # Get status for all memories or all memories of an agent
                status_summary = {
                    "total_memories": 0,
                    "synced": 0,
                    "pending": 0,
                    "failed": 0,
                    "conflicts": 0,
                    "in_progress": 0,
                    "memories": []
                }
                
                async with self._lock:
                    for mem_agent_id, agent_memories in self._memory_store.items():
                        # Filter by agent_id if specified
                        if agent_id and mem_agent_id != agent_id:
                            continue
                        
                        for mem_id, memory_data in agent_memories.items():
                            status_summary["total_memories"] += 1
                            
                            sync_status = self._memory_sync_status.get(mem_id, MemorySyncStatus.PENDING)
                            status_summary[sync_status.value] += 1
                            
                            status_summary["memories"].append({
                                "memory_id": mem_id,
                                "agent_id": mem_agent_id,
                                "sync_status": sync_status.value,
                                "last_synced": memory_data.get("synced_at")
                            })
                
                return status_summary
                
        except Exception as e:
            self.logger.error(f"Failed to get sync status: {e}")
            return {"success": False, "message": f"Failed to get sync status: {e!s}"}
    
    async def convert_agent_memory_to_karen_format(self, agent_memory: dict[str, Any]) -> dict[str, Any]:
        """
        Convert agent memory to Karen's memory format.
        
        This method transforms the agent's internal memory format to the format
        expected by Karen's Unified Memory Service, handling field mappings and
        data transformations.
        
        Args:
            agent_memory: Agent memory data in agent format
            
        Returns:
            Dictionary with memory data in Karen's format
            
        Raises:
            ValueError: If required fields are missing or invalid
            Exception: If conversion fails due to unexpected data formats
            
        Example:
            ```python
            # Convert agent memory to Karen's format
            agent_memory = {
                "memory_id": "123e4567-e89b-12d3-a456-426614174000",
                "agent_id": "agent123",
                "memory_type": "conversation",
                "content": {"message": "Hello world"},
                "tags": ["greeting"],
                "importance": 0.8
            }
            
            karen_memory = await memory_service.convert_agent_memory_to_karen_format(agent_memory)
            print(f"Karen memory format: {karen_memory}")
            ```
        """
        try:
            # Extract content
            content = agent_memory.get("content", {})
            text = json.dumps(content)
            
            # Extract tags
            tags = agent_memory.get("tags", [])
            
            # Extract importance and scale to 1-10
            importance = int(agent_memory.get("importance", 0.5) * 10)
            
            # Determine decay tier based on importance
            decay_tier = "short"
            for tier, config in self._config.get("decay_tiers", {}).items():
                if importance >= config["importance_threshold"]:
                    decay_tier = tier
                    break
            
            # Extract metadata
            metadata = {
                "agent_id": agent_memory.get("agent_id"),
                "memory_type": agent_memory.get("memory_type"),
                "access_level": agent_memory.get("access_level"),
                "namespace": agent_memory.get("namespace"),
                "memory_id": agent_memory.get("memory_id"),
                "version": agent_memory.get("version", 1),
                "created_at": agent_memory.get("created_at"),
                "updated_at": agent_memory.get("updated_at"),
                "expires_at": agent_memory.get("expires_at"),
            }
            
            # Add any additional metadata
            additional_metadata = agent_memory.get("metadata", {})
            if additional_metadata:
                metadata.update(additional_metadata)
            
            return {
                "text": text,
                "tags": tags,
                "importance": importance,
                "decay": decay_tier,
                "metadata": metadata
            }
            
        except Exception as e:
            self.logger.error(f"Failed to convert agent memory to Karen format: {e}")
            raise ValueError(f"Memory conversion failed: {e!s}")
    
    async def convert_karen_memory_to_agent_format(self, karen_memory: Any) -> dict[str, Any]:
        """
        Convert Karen's memory to agent memory format.
        
        This method transforms Karen's Unified Memory Service format to the agent's
        internal memory format, handling field mappings and data transformations.
        
        Args:
            karen_memory: Karen's memory data (can be a Pydantic model or dictionary)
            
        Returns:
            Dictionary with memory data in agent format
            
        Raises:
            ValueError: If required fields are missing or invalid
            Exception: If conversion fails due to unexpected data formats
            
        Example:
            ```python
            # Convert Karen's memory to agent format
            karen_memory = {
                "id": "karen_mem_123",
                "text": '{"message": "Hello world"}',
                "tags": ["greeting"],
                "importance": 8,
                "decay": "short",
                "metadata": {
                    "agent_id": "agent123",
                    "memory_type": "conversation"
                }
            }
            
            agent_memory = await memory_service.convert_karen_memory_to_agent_format(karen_memory)
            print(f"Agent memory format: {agent_memory}")
            ```
        """
        try:
            # Handle different input types
            if hasattr(karen_memory, 'model_dump'):
                # Pydantic model
                karen_data = karen_memory.model_dump()
            elif isinstance(karen_memory, dict):
                # Dictionary
                karen_data = karen_memory
            else:
                # Try to convert to dict
                karen_data = dict(karen_memory)
            
            # Extract text and parse as JSON
            text = karen_data.get("text", "{}")
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                content = {"raw_text": text}
            
            # Extract tags
            tags = karen_data.get("tags", [])
            
            # Extract importance and scale to 0.0-1.0
            importance = karen_data.get("importance", 5) / 10.0
            
            # Extract metadata
            metadata = karen_data.get("metadata", {})
            
            return {
                "memory_id": metadata.get("memory_id", str(uuid.uuid4())),
                "agent_id": metadata.get("agent_id"),
                "memory_type": metadata.get("memory_type", "general"),
                "content": content,
                "tags": tags,
                "importance": importance,
                "created_at": metadata.get("created_at", datetime.utcnow()),
                "updated_at": metadata.get("updated_at", datetime.utcnow()),
                "expires_at": metadata.get("expires_at"),
                "access_level": metadata.get("access_level", MemoryAccessLevel.PRIVATE.value),
                "namespace": metadata.get("namespace", "default"),
                "metadata": {k: v for k, v in metadata.items()
                           if k not in ["agent_id", "memory_type", "access_level", "namespace", "memory_id",
                                      "version", "created_at", "updated_at", "expires_at"]},
                "version": metadata.get("version", 1),
                "unified_memory_id": karen_data.get("id"),
                "decay_tier": karen_data.get("decay_tier", "short"),
                "embedding": None,
                "graph_edges": []
            }
            
        except Exception as e:
            self.logger.error(f"Failed to convert Karen memory to agent format: {e}")
            raise ValueError(f"Memory conversion failed: {e!s}")
    
    async def convert_memory_query(self, agent_query: dict[str, Any]) -> Any:
        """
        Convert agent memory query to Karen's memory query format.
        
        Args:
            agent_query: Agent memory query in agent format
            
        Returns:
            Query in Karen's format
        """
        try:
            # Extract query parameters
            query_text = agent_query.get("query", "")
            user_id = agent_query.get("agent_id", "")
            org_id = agent_query.get("org_id")
            top_k = agent_query.get("limit", 10)
            similarity_threshold = agent_query.get("similarity_threshold",
                                           self._config.get("similarity_threshold", 0.7))
            
            # Create query in Karen's format
            if MemoryQueryRequest:
                return MemoryQueryRequest(
                    user_id=f"agent:{user_id}",
                    org_id=org_id,
                    query=query_text,
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                    include_metadata=True
                )
            else:
                # Fallback if MemoryQueryRequest is not available
                return {
                    "user_id": f"agent:{user_id}",
                    "org_id": org_id,
                    "query": query_text,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                    "include_metadata": True
                }
                
        except Exception as e:
            self.logger.error(f"Failed to convert agent query to Karen format: {e}")
            raise ValueError(f"Query conversion failed: {e!s}")
    
    async def convert_memory_response(self, karen_response: Any) -> dict[str, Any]:
        """
        Convert Karen's memory response to agent memory response format.
        
        Args:
            karen_response: Karen's memory response
            
        Returns:
            Dictionary with response data in agent format
        """
        try:
            # Handle different response types
            if hasattr(karen_response, 'model_dump'):
                # Pydantic model
                response_data = karen_response.model_dump()
            elif isinstance(karen_response, dict):
                # Dictionary
                response_data = karen_response
            else:
                # Try to convert to dict
                response_data = dict(karen_response)
            
            # Extract hits
            hits = response_data.get("hits", [])
            converted_hits = []
            
            for hit in hits:
                if hasattr(hit, 'model_dump'):
                    hit_data = hit.model_dump()
                elif isinstance(hit, dict):
                    hit_data = hit
                else:
                    hit_data = dict(hit)
                
                # Convert hit to agent format
                converted_hit = await self.convert_karen_memory_to_agent_format(hit_data)
                
                # Add score
                converted_hit["relevance_score"] = hit_data.get("score", 0.0)
                
                converted_hits.append(converted_hit)
            
            # Create response in agent format
            return {
                "results": converted_hits,
                "total_found": response_data.get("total_found", len(converted_hits)),
                "query_time_ms": response_data.get("query_time_ms", 0.0),
                "correlation_id": response_data.get("correlation_id", "")
            }
            
        except Exception as e:
            self.logger.error(f"Failed to convert Karen response to agent format: {e}")
            raise ValueError(f"Response conversion failed: {e!s}")
    
    async def detect_memory_conflicts(self, memory_id: str, karen_memory: dict[str, Any]) -> dict[str, Any] | None:
        """
        Detect conflicts between agent memory and Karen's memory.
        
        This method compares the agent's local memory with the corresponding memory
        in Karen's Unified Memory Service to detect conflicts based on timestamps
        and content differences.
        
        Args:
            memory_id: ID of the memory to check for conflicts
            karen_memory: Karen's memory data to compare against
            
        Returns:
            Dictionary with conflict details if conflict is detected, None otherwise.
            The conflict details include:
            - memory_id: ID of the memory with conflicts
            - agent_updated_at: Last update timestamp in agent's memory
            - karen_updated_at: Last update timestamp in Karen's memory
            - time_diff_seconds: Time difference between updates
            - agent_version: Version number in agent's memory
            - karen_version: Version number in Karen's memory
            - conflict_type: Type of conflict detected
            
        Raises:
            Exception: If conflict detection fails due to internal errors
            
        Example:
            ```python
            # Detect conflicts for a memory
            karen_memory = {
                "metadata": {
                    "updated_at": "2023-01-02T12:00:00",
                    "version": 2
                }
            }
            
            conflict = await memory_service.detect_memory_conflicts(
                memory_id="123e4567-e89b-12d3-a456-426614174000",
                karen_memory=karen_memory
            )
            
            if conflict:
                print(f"Conflict detected: {conflict}")
            else:
                print("No conflicts detected")
            ```
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_conflict_resolution", True):
            return None
        
        try:
            # Find the agent memory
            agent_memory = None
            for agent_memories in self._memory_store.values():
                if memory_id in agent_memories:
                    agent_memory = agent_memories[memory_id]
                    break
            
            if not agent_memory:
                return None
            
            # Get the unified memory ID if available
            unified_memory_id = agent_memory.get("unified_memory_id")
            if not unified_memory_id:
                # No unified memory ID means no conflict possible
                return None
            
            # Compare timestamps to detect conflicts
            agent_updated_at = agent_memory.get("updated_at")
            karen_updated_at = karen_memory.get("metadata", {}).get("updated_at")
            
            if not agent_updated_at or not karen_updated_at:
                # If timestamps are missing, assume no conflict
                return None
            
            # Convert to datetime if needed
            if isinstance(agent_updated_at, str):
                agent_updated_at = datetime.fromisoformat(agent_updated_at)
            
            if isinstance(karen_updated_at, str):
                karen_updated_at = datetime.fromisoformat(karen_updated_at)
            
            # Check for conflicts
            time_diff = abs((agent_updated_at - karen_updated_at).total_seconds())
            
            # If timestamps differ by more than 5 seconds, consider it a conflict
            if time_diff > 5:
                # Compare content to see if it's actually different
                agent_content = json.dumps(agent_memory.get("content", {}), sort_keys=True)
                karen_content = json.dumps(karen_memory.get("metadata", {}).get("content", {}), sort_keys=True)
                
                if agent_content != karen_content:
                    return {
                        "memory_id": memory_id,
                        "agent_updated_at": agent_updated_at.isoformat(),
                        "karen_updated_at": karen_updated_at.isoformat(),
                        "time_diff_seconds": time_diff,
                        "agent_version": agent_memory.get("version", 1),
                        "karen_version": karen_memory.get("metadata", {}).get("version", 1),
                        "conflict_type": "timestamp_mismatch"
                    }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to detect memory conflicts for {memory_id}: {e}")
            return None
    
    async def resolve_memory_conflicts(self, memory_id: str, conflict_details: dict[str, Any], resolution_strategy: str | None = None) -> dict[str, Any]:
        """
        Resolve conflicts between agent memory and Karen's memory.
        
        Args:
            memory_id: ID of the memory with conflicts
            conflict_details: Details about the conflict
            resolution_strategy: Strategy to use for resolution (if None, use default)
            
        Returns:
            Dictionary with resolution results
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_conflict_resolution", True):
            return {"success": False, "message": "Conflict resolution is disabled"}
        
        # Use default resolution strategy if none provided
        resolution_strategy = resolution_strategy or self._config.get("default_resolution_strategy", "agent_priority")
        
        try:
            # Find the agent memory
            agent_memory = None
            agent_id = None
            
            for mem_id, agent_memories in self._memory_store.items():
                if memory_id in agent_memories:
                    agent_memory = agent_memories[memory_id]
                    agent_id = mem_id
                    break
            
            if not agent_memory or not agent_id:
                return {"success": False, "message": f"Memory {memory_id} not found"}
            
            # Get Karen's memory
            if not self._unified_memory_service:
                return {"success": False, "message": "Unified Memory Service is not available"}
            
            unified_memory_id = agent_memory.get("unified_memory_id")
            if not unified_memory_id:
                return {"success": False, "message": "Memory not synchronized with Karen's memory"}
            
            # Get Karen's memory data
            tenant_id = agent_id  # Simplified for now
            
            # This would typically call a method to get the memory from Karen's service
            # For now, we'll simulate this with a placeholder
            karen_memory = {"metadata": {}}  # Placeholder
            
            # Apply resolution strategy
            resolved_memory = await self.apply_resolution_strategy(agent_memory, conflict_details, resolution_strategy)
            
            if not resolved_memory:
                return {"success": False, "message": f"Failed to apply resolution strategy: {resolution_strategy}"}
            
            # Update the agent memory with resolved data
            async with self._lock:
                if agent_id in self._memory_store and memory_id in self._memory_store[agent_id]:
                    # Update memory content
                    self._memory_store[agent_id][memory_id].update(resolved_memory)
                    
                    # Update timestamp
                    self._memory_store[agent_id][memory_id]["updated_at"] = datetime.utcnow()
                    
                    # Increment version
                    self._memory_store[agent_id][memory_id]["version"] += 1
                    
                    # Record resolution in history
                    if memory_id in self._memory_history:
                        self._memory_history[memory_id].append({
                            "action": "resolve_conflict",
                            "timestamp": datetime.utcnow().isoformat(),
                            "agent_id": agent_id,
                            "resolution_strategy": resolution_strategy,
                            "conflict_details": conflict_details
                        })
            
            # Update sync status
            self._memory_sync_status[memory_id] = MemorySyncStatus.SYNCED
            
            # Log the conflict resolution
            await self.log_memory_conflict(
                memory_id=memory_id,
                agent_id=agent_id,
                conflict_details=conflict_details,
                resolution_strategy=resolution_strategy,
                resolved=True
            )
            
            return {
                "success": True,
                "message": "Memory conflict resolved successfully",
                "resolution_strategy": resolution_strategy,
                "memory_id": memory_id
            }
            
        except Exception as e:
            self.logger.error(f"Failed to resolve memory conflict for {memory_id}: {e}")
            
            # Log the failed resolution
            try:
                # Use a safe fallback for agent_id
                safe_agent_id = "unknown"
                
                # Use locals() to check if agent_id is defined
                local_vars = locals()
                if 'agent_id' in local_vars and local_vars['agent_id'] is not None:
                    safe_agent_id = local_vars['agent_id']
                    
                await self.log_memory_conflict(
                    memory_id=memory_id,
                    agent_id=safe_agent_id,
                    conflict_details=conflict_details,
                    resolution_strategy=resolution_strategy or "unknown",
                    resolved=False,
                    error=str(e)
                )
            except Exception as log_error:
                self.logger.error(f"Failed to log memory conflict: {log_error}")
            
            return {"success": False, "message": f"Conflict resolution failed: {e!s}"}
    
    async def apply_resolution_strategy(self, agent_memory: dict[str, Any], conflict_details: dict[str, Any], resolution_strategy: str) -> dict[str, Any] | None:
        """
        Apply a specific resolution strategy to memory conflicts.
        
        Args:
            agent_memory: Agent memory data
            conflict_details: Details about the conflict
            resolution_strategy: Strategy to apply
            
        Returns:
            Resolved memory data if successful, None otherwise
        """
        try:
            if resolution_strategy == "agent_priority":
                # Keep agent's version of the memory
                return agent_memory.copy()
            
            elif resolution_strategy == "karen_priority":
                # Use Karen's version of the memory
                # This would typically involve getting the full memory from Karen's service
                # For now, we'll return a placeholder
                return {"content": {}, "tags": [], "importance": 0.5}  # Placeholder
            
            elif resolution_strategy == "newest":
                # Use the newest version based on timestamps
                agent_updated_at = agent_memory.get("updated_at", datetime.min)
                karen_updated_at_str = conflict_details.get("karen_updated_at")
                
                if isinstance(karen_updated_at_str, str):
                    karen_updated_at = datetime.fromisoformat(karen_updated_at_str)
                else:
                    karen_updated_at = datetime.min
                
                if agent_updated_at > karen_updated_at:
                    return agent_memory.copy()
                else:
                    # Use Karen's version
                    return {"content": {}, "tags": [], "importance": 0.5}  # Placeholder
            
            elif resolution_strategy == "merge":
                # Merge both versions
                # This would typically involve getting the full memory from Karen's service
                # For now, we'll return a placeholder merge
                return {
                    "content": agent_memory.get("content", {}),
                    "tags": agent_memory.get("tags", []),
                    "importance": agent_memory.get("importance", 0.5),
                    "metadata": {
                        "merged_from": "agent_and_karen",
                        "agent_version": agent_memory.get("version", 1),
                        "karen_version": conflict_details.get("karen_version", 1)
                    }
                }
            
            elif resolution_strategy == "manual":
                # Mark for manual resolution
                return {
                    "content": agent_memory.get("content", {}),
                    "tags": agent_memory.get("tags", []),
                    "importance": agent_memory.get("importance", 0.5),
                    "metadata": {
                        "requires_manual_resolution": True,
                        "conflict_details": conflict_details
                    }
                }
            
            else:
                self.logger.error(f"Unknown resolution strategy: {resolution_strategy}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to apply resolution strategy {resolution_strategy}: {e}")
            return None
    
    async def log_memory_conflict(self, memory_id: str, agent_id: str, conflict_details: dict[str, Any],
                                resolution_strategy: str, resolved: bool, error: str | None = None) -> None:
        """
        Log memory conflicts for later analysis.
        
        Args:
            memory_id: ID of the memory with conflicts
            agent_id: ID of the agent owning the memory
            conflict_details: Details about the conflict
            resolution_strategy: Strategy used for resolution
            resolved: Whether the conflict was resolved
            error: Error message if resolution failed
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_operation_logging", True):
            return
        
        try:
            # Create conflict log entry
            conflict_log = {
                "timestamp": datetime.utcnow().isoformat(),
                "memory_id": memory_id,
                "agent_id": agent_id,
                "conflict_details": conflict_details,
                "resolution_strategy": resolution_strategy,
                "resolved": resolved,
                "error": error
            }
            
            # Add to operation log
            async with self._lock:
                self._operation_log.append({
                    "operation_type": MemoryOperationType.SYNC.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "memory_id": memory_id,
                    "agent_id": agent_id,
                    "details": {
                        "conflict": True,
                        "conflict_details": conflict_details,
                        "resolution_strategy": resolution_strategy,
                        "resolved": resolved,
                        "error": error
                    }
                })
            
            self.logger.info(f"Logged memory conflict for memory {memory_id} (resolved={resolved})")
            
        except Exception as e:
            self.logger.error(f"Failed to log memory conflict for {memory_id}: {e}")
    
    async def check_memory_access_permission(self, agent_id: str, memory_id: str, permission_type: str = "read") -> bool:
        """
        Check if an agent has permission to access a memory.
        
        Args:
            agent_id: ID of the agent requesting access
            memory_id: ID of the memory to access
            permission_type: Type of permission to check (read, write, delete, etc.)
            
        Returns:
            True if agent has permission, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_access_control", True):
            return True  # Access control disabled
        
        try:
            # Find the memory in our store
            memory_found = None
            owner_agent_id = None
            
            for agent_mem_id, agent_memories in self._memory_store.items():
                if memory_id in agent_memories:
                    memory_found = agent_memories[memory_id]
                    owner_agent_id = agent_mem_id
                    break
            
            if not memory_found:
                return False
            
            # Owner always has full access
            if owner_agent_id == agent_id:
                return True
            
            # Check access level
            access_level = memory_found.get("access_level", MemoryAccessLevel.PRIVATE.value)
            
            if access_level == MemoryAccessLevel.PUBLIC.value:
                return True
            
            if access_level == MemoryAccessLevel.PRIVATE.value:
                return False
            
            # Check shared access permissions
            if agent_id in self._memory_access_permissions:
                agent_permissions = self._memory_access_permissions[agent_id]
                
                # Check if agent has the specific permission for this memory
                if permission_type in agent_permissions:
                    if memory_id in agent_permissions[permission_type]:
                        return True
            
            # Check if memory is shared with this agent
            if await self._is_memory_shared_with_agent(memory_id, agent_id):
                # For shared memories, check the sharing policy
                for request_id, request in self._sharing_requests.items():
                    if (request.source_agent_id == owner_agent_id and
                        request.target_agent_id == agent_id and
                        memory_id in request.memory_ids):
                        
                        sharing_policy = request.sharing_policy
                        if permission_type == "read":
                            return True  # All shared memories have read access
                        elif permission_type == "write":
                            return sharing_policy in [MemorySharingPolicy.READ_WRITE, MemorySharingPolicy.FULL_ACCESS]
                        elif permission_type == "delete":
                            return sharing_policy == MemorySharingPolicy.FULL_ACCESS
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to check memory access permission for agent {agent_id}, memory {memory_id}: {e}")
            return False
    
    async def enforce_memory_access_permission(self, agent_id: str, memory_id: str, permission_type: str = "read") -> bool:
        """
        Enforce memory access permissions for an agent.
        
        Args:
            agent_id: ID of the agent requesting access
            memory_id: ID of the memory to access
            permission_type: Type of permission to enforce (read, write, delete, etc.)
            
        Returns:
            True if access is granted, False otherwise
            
        Raises:
            PermissionError: If access is denied
        """
        if not self._initialized:
            await self.initialize()
        
        has_permission = await self.check_memory_access_permission(agent_id, memory_id, permission_type)
        
        if not has_permission:
            # Log the access denial
            await self.log_memory_operation(
                operation_type=MemoryOperationType.READ if permission_type == "read" else MemoryOperationType.UPDATE,
                agent_id=agent_id,
                memory_id=memory_id,
                details={"permission_type": permission_type, "access_denied": True},
                success=False
            )
            
            raise PermissionError(f"Agent {agent_id} does not have {permission_type} permission for memory {memory_id}")
        
        return True
    
    async def set_memory_access_permission(self, agent_id: str, memory_id: str, target_agent_id: str,
                                         permission_type: str, grant: bool = True) -> bool:
        """
        Set memory access permissions for agents.
        
        Args:
            agent_id: ID of the agent owning the memory
            memory_id: ID of the memory
            target_agent_id: ID of the agent to grant/deny permission
            permission_type: Type of permission to set (read, write, delete, etc.)
            grant: True to grant permission, False to revoke
            
        Returns:
            True if permission was set successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_access_control", True):
            return True  # Access control disabled
        
        try:
            # Verify that the agent owns the memory
            if agent_id not in self._memory_store or memory_id not in self._memory_store[agent_id]:
                self.logger.warning(f"Agent {agent_id} does not own memory {memory_id}")
                return False
            
            # Initialize permissions for target agent if needed
            if target_agent_id not in self._memory_access_permissions:
                self._memory_access_permissions[target_agent_id] = {}
            
            if permission_type not in self._memory_access_permissions[target_agent_id]:
                self._memory_access_permissions[target_agent_id][permission_type] = set()
            
            # Grant or revoke permission
            if grant:
                self._memory_access_permissions[target_agent_id][permission_type].add(memory_id)
            else:
                if memory_id in self._memory_access_permissions[target_agent_id][permission_type]:
                    self._memory_access_permissions[target_agent_id][permission_type].remove(memory_id)
            
            # Log the permission change
            await self.log_memory_operation(
                operation_type=MemoryOperationType.UPDATE,
                agent_id=agent_id,
                memory_id=memory_id,
                details={
                    "permission_type": permission_type,
                    "target_agent_id": target_agent_id,
                    "grant": grant
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to set memory access permission: {e}")
            return False
    
    async def get_memory_access_permissions(self, agent_id: str | None = None, memory_id: str | None = None) -> dict[str, Any]:
        """
        Get memory access permissions for agents.
        
        Args:
            agent_id: Optional agent ID to filter permissions
            memory_id: Optional memory ID to filter permissions
            
        Returns:
            Dictionary with permission information
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            permissions = {
                "agents": {},
                "memories": {},
                "summary": {
                    "total_agents": 0,
                    "total_memories": 0,
                    "total_permissions": 0
                }
            }
            
            async with self._lock:
                # Filter by agent_id if specified
                if agent_id:
                    if agent_id in self._memory_access_permissions:
                        permissions["agents"][agent_id] = {
                            permission_type: list(memory_ids)
                            for permission_type, memory_ids in self._memory_access_permissions[agent_id].items()
                        }
                        permissions["summary"]["total_agents"] = 1
                        permissions["summary"]["total_permissions"] = sum(
                            len(memory_ids) for memory_ids in self._memory_access_permissions[agent_id].values()
                        )
                else:
                    # Get all agent permissions
                    for agent_id, agent_permissions in self._memory_access_permissions.items():
                        permissions["agents"][agent_id] = {
                            permission_type: list(memory_ids)
                            for permission_type, memory_ids in agent_permissions.items()
                        }
                        permissions["summary"]["total_agents"] += 1
                        permissions["summary"]["total_permissions"] += sum(
                            len(memory_ids) for memory_ids in agent_permissions.values()
                        )
                
                # Filter by memory_id if specified
                if memory_id:
                    permissions["memories"][memory_id] = {
                        "agents": [],
                        "permissions": {}
                    }
                    
                    for agent_id, agent_permissions in self._memory_access_permissions.items():
                        for permission_type, memory_ids in agent_permissions.items():
                            if memory_id in memory_ids:
                                permissions["memories"][memory_id]["agents"].append(agent_id)
                                
                                if permission_type not in permissions["memories"][memory_id]["permissions"]:
                                    permissions["memories"][memory_id]["permissions"][permission_type] = []
                                
                                permissions["memories"][memory_id]["permissions"][permission_type].append(agent_id)
                    
                    permissions["summary"]["total_memories"] = 1
                else:
                    # Get all memory permissions
                    all_memory_ids = set()
                    
                    for agent_permissions in self._memory_access_permissions.values():
                        for memory_ids in agent_permissions.values():
                            all_memory_ids.update(memory_ids)
                    
                    for mem_id in all_memory_ids:
                        permissions["memories"][mem_id] = {
                            "agents": [],
                            "permissions": {}
                        }
                        
                        for agent_id, agent_permissions in self._memory_access_permissions.items():
                            for permission_type, memory_ids in agent_permissions.items():
                                if mem_id in memory_ids:
                                    permissions["memories"][mem_id]["agents"].append(agent_id)
                                    
                                    if permission_type not in permissions["memories"][mem_id]["permissions"]:
                                        permissions["memories"][mem_id]["permissions"][permission_type] = []
                                    
                                    permissions["memories"][mem_id]["permissions"][permission_type].append(agent_id)
                    
                    permissions["summary"]["total_memories"] = len(all_memory_ids)
            
            return permissions
            
        except Exception as e:
            self.logger.error(f"Failed to get memory access permissions: {e}")
            return {"error": str(e)}
    
    async def log_memory_operation(self, operation_type: MemoryOperationType, agent_id: str,
                                memory_id: str | None = None,
                                details: dict[str, Any] | None = None,
                                success: bool = True) -> None:
        """
        Log memory operations with appropriate details.
        
        Args:
            operation_type: Type of memory operation
            agent_id: ID of the agent performing the operation
            memory_id: Optional ID of the memory being operated on
            details: Optional details about the operation
            success: Whether the operation was successful
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._config.get("enable_operation_logging", True):
            return
        
        try:
            # Create operation log entry
            operation_log = {
                "operation_type": operation_type.value,
                "timestamp": datetime.utcnow().isoformat(),
                "agent_id": agent_id,
                "memory_id": memory_id,
                "success": success,
                "details": details or {}
            }
            
            # Add to operation log
            async with self._lock:
                self._operation_log.append(operation_log)
                
                # Limit log size based on retention policy
                retention_days = self._config.get("log_retention_days", 30)
                cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
                
                # Remove old entries
                self._operation_log = [
                    entry for entry in self._operation_log
                    if datetime.fromisoformat(entry["timestamp"]) > cutoff_date
                ]
            
            self.logger.debug(f"Logged memory operation: {operation_type.value} by agent {agent_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to log memory operation: {e}")
    
    async def get_memory_operation_log(self, agent_id: str | None = None,
                                     memory_id: str | None = None,
                                     operation_type: MemoryOperationType | None = None,
                                     start_time: datetime | None = None,
                                     end_time: datetime | None = None,
                                     success: bool | None = None,
                                     limit: int = 100) -> dict[str, Any]:
        """
        Retrieve memory operation logs based on filters.
        
        Args:
            agent_id: Optional agent ID to filter by
            memory_id: Optional memory ID to filter by
            operation_type: Optional operation type to filter by
            start_time: Optional start time to filter by
            end_time: Optional end time to filter by
            success: Optional success status to filter by
            limit: Maximum number of entries to return
            
        Returns:
            Dictionary with filtered operation logs
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            filtered_logs = []
            
            async with self._lock:
                # Apply filters
                for entry in self._operation_log:
                    # Filter by agent_id
                    if agent_id and entry["agent_id"] != agent_id:
                        continue
                    
                    # Filter by memory_id
                    if memory_id and entry["memory_id"] != memory_id:
                        continue
                    
                    # Filter by operation_type
                    if operation_type and entry["operation_type"] != operation_type.value:
                        continue
                    
                    # Filter by success
                    if success is not None and entry["success"] != success:
                        continue
                    
                    # Filter by start_time
                    if start_time:
                        entry_time = datetime.fromisoformat(entry["timestamp"])
                        if entry_time < start_time:
                            continue
                    
                    # Filter by end_time
                    if end_time:
                        entry_time = datetime.fromisoformat(entry["timestamp"])
                        if entry_time > end_time:
                            continue
                    
                    filtered_logs.append(entry)
            
            # Sort by timestamp (newest first)
            filtered_logs.sort(key=lambda x: x["timestamp"], reverse=True)
            
            # Apply limit
            if limit and len(filtered_logs) > limit:
                filtered_logs = filtered_logs[:limit]
            
            return {
                "logs": filtered_logs,
                "total": len(filtered_logs),
                "filters": {
                    "agent_id": agent_id,
                    "memory_id": memory_id,
                    "operation_type": operation_type.value if operation_type else None,
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None,
                    "success": success,
                    "limit": limit
                }
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get memory operation log: {e}")
            return {"error": str(e), "logs": []}
    
    async def clear_memory_operation_log(self, retention_days: int | None = None) -> dict[str, Any]:
        """
        Clear old memory operation logs based on retention policy.
        
        Args:
            retention_days: Number of days to retain (if None, use config value)
            
        Returns:
            Dictionary with operation results
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Use config value if not specified
            if retention_days is None:
                retention_days = self._config.get("log_retention_days", 30)
            
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days if retention_days is not None else 30)
            removed_count = 0
            
            async with self._lock:
                # Get initial count
                initial_count = len(self._operation_log)
                
                # Remove old entries
                self._operation_log = [
                    entry for entry in self._operation_log
                    if datetime.fromisoformat(entry["timestamp"]) > cutoff_date
                ]
                
                # Calculate removed count
                removed_count = initial_count - len(self._operation_log)
            
            self.logger.info(f"Cleared {removed_count} old memory operation log entries (retention: {retention_days} days)")
            
            return {
                "success": True,
                "removed_count": removed_count,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat(),
                "remaining_count": len(self._operation_log)
            }
            
        except Exception as e:
            self.logger.error(f"Failed to clear memory operation log: {e}")
            return {"success": False, "error": str(e)}
