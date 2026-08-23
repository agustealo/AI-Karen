"""
Agent Registry service for managing agent registration and discovery.

This service maintains a registry of all available agents in the system,
their capabilities, and current status.
"""

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Dict, Any, List, Optional, Set, Tuple, Union, Callable
from datetime import datetime, timedelta
from enum import Enum
from uuid import uuid4
import numpy as np
import networkx as nx
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.integrations.auth_manager import AuthenticationManager as AuthManager

# Try to import UnifiedMemoryService, but handle if it's not available
try:
    from ai_karen_engine.core.memory.unified_memory_service import UnifiedMemoryService
    HAS_MEMORY_SERVICE = True
except ImportError:
    HAS_MEMORY_SERVICE = False
    UnifiedMemoryService = None

from .internal.agent_schemas import (
    AgentDefinition, AgentCapability, AgentStatus,
    AgentTask, AgentResponse, AgentSession
)
from .internal.agent_validation import AgentValidation
from .internal.agent_metrics import AgentMetrics

logger = logging.getLogger(__name__)


class AgentHealthStatus(str, Enum):
    """Agent health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AgentLifecycleEvent(str, Enum):
    """Agent lifecycle event enumeration."""
    REGISTERED = "registered"
    DEREGISTERED = "deregistered"
    UPDATED = "updated"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"
    HEALTH_CHECK = "health_check"
    HEARTBEAT = "heartbeat"
    DISCOVERED = "discovered"
    RECONNECTED = "reconnected"
    CAPABILITY_BROADCAST = "capability_broadcast"


@dataclass
class AgentHeartbeat:
    """Agent heartbeat data structure."""
    agent_id: str
    timestamp: datetime
    status: AgentHealthStatus
    endpoint: str
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    resource_usage: Dict[str, float] = field(default_factory=dict)


@dataclass
class AgentNetworkTopology:
    """Agent network topology information."""
    agent_id: str
    neighbors: Set[str] = field(default_factory=set)
    network_distance: Dict[str, int] = field(default_factory=dict)
    network_position: Tuple[float, float] = (0.0, 0.0)  # x, y coordinates for visualization
    connection_quality: Dict[str, float] = field(default_factory=dict)  # Quality metrics to neighbors


@dataclass
class CapabilityEmbedding:
    """Vector embedding for agent capabilities."""
    capability: str
    embedding: np.ndarray
    version: str = "1.0"
    last_updated: datetime = field(default_factory=datetime.utcnow)


class CapabilityHierarchy:
    """Manages capability hierarchy and inheritance."""
    
    def __init__(self):
        self._parent_child_map: Dict[str, Set[str]] = defaultdict(set)
        self._child_parent_map: Dict[str, str] = {}
        self._capability_attributes: Dict[str, Dict[str, Any]] = defaultdict(dict)
    
    def add_capability(self, capability: str, parent: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None):
        """Add a capability to the hierarchy."""
        if parent:
            self._parent_child_map[parent].add(capability)
            self._child_parent_map[capability] = parent
        
        if attributes:
            self._capability_attributes[capability] = attributes
    
    def get_children(self, capability: str) -> Set[str]:
        """Get all child capabilities of a given capability."""
        return self._parent_child_map.get(capability, set())
    
    def get_parent(self, capability: str) -> Optional[str]:
        """Get the parent of a capability."""
        return self._child_parent_map.get(capability)
    
    def get_all_descendants(self, capability: str) -> Set[str]:
        """Get all descendant capabilities (children, grandchildren, etc.)."""
        descendants = set()
        for child in self.get_children(capability):
            descendants.add(child)
            descendants.update(self.get_all_descendants(child))
        return descendants
    
    def get_attributes(self, capability: str) -> Dict[str, Any]:
        """Get attributes of a capability."""
        return self._capability_attributes.get(capability, {})


class AgentRegistry(BaseService):
    """
    Enhanced Agent Registry service for managing agent registration, discovery, and lifecycle.
    
    This service maintains a registry of all available agents in the system,
    their capabilities, metadata, health status, and provides functionality for
    registering, unregistering, discovering, and managing agents.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_registry"))
        self._initialized = False
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=10)
        
        # Configuration
        self._config = config or ServiceConfig(name="agent_registry")
        self._auto_register_discovered = True
        
        # Core services
        self._validation_service: Optional[AgentValidation] = None
        self._metrics_service: Optional[AgentMetrics] = None
        self._auth_manager: Optional[AuthManager] = None
        self._memory_service: Optional[Any] = None
        
        # Agent storage
        self._agents: Dict[str, AgentDefinition] = {}
        self._agent_instances: Dict[str, Dict[str, Any]] = {}
        self._agent_metadata: Dict[str, Dict[str, Any]] = {}
        self._agent_health: Dict[str, Dict[str, Any]] = {}
        self._agent_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._agent_versions: Dict[str, Dict[str, Any]] = {}
        
        # Dynamic agent discovery
        self._agent_heartbeats: Dict[str, AgentHeartbeat] = {}
        self._discovery_active = False
        self._discovery_interval = 30  # seconds
        
        # Enhanced dynamic discovery attributes
        self._discovery_enabled = False
        self._discovery_interval_minutes = 5  # minutes
        self._discovered_agents: Dict[str, Dict[str, Any]] = {}
        self._discovery_sources: List[Dict[str, Any]] = []
        self._discovery_tasks: Dict[str, asyncio.Task] = {}
        self._heartbeat_interval = 10  # seconds
        self._reconnection_attempts = 3
        self._reconnection_delay = 5  # seconds
        self._network_topology: Dict[str, AgentNetworkTopology] = {}
        self._network_graph = nx.Graph()
        
        # Capability indexing
        self._capability_index: Dict[str, Set[str]] = defaultdict(set)
        self._semantic_index: Dict[str, List[str]] = defaultdict(list)
        self._category_index: Dict[str, Set[str]] = defaultdict(set)
        self._tag_index: Dict[str, Set[str]] = defaultdict(set)
        
        # Advanced capability indexing
        self._capability_embeddings: Dict[str, CapabilityEmbedding] = {}
        self._embedding_dimension = 128  # Dimension for capability embeddings
        self._capability_hierarchy = CapabilityHierarchy()
        self._embedding_model = None  # Will be initialized when needed
        
        # Agent relationships
        self._agent_relationships: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: {
            "depends_on": [],
            "used_by": [],
            "similar": [],
            "complementary": []
        })
        
        # Performance and health tracking
        self._agent_performance: Dict[str, Dict[str, Any]] = {}
        self._resource_usage_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._anomaly_detection_threshold = 2.0  # Standard deviations for anomaly detection
        
        # Configuration management
        self._agent_configs: Dict[str, Dict[str, Any]] = {}
        self._config_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Lifecycle event handling
        self._event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._event_history: deque = deque(maxlen=1000)
        
        # Background tasks
        self._health_monitor_task = None
        self._cleanup_task = None
        self._analytics_task = None
        self._discovery_task = None
        self._heartbeat_task = None
        self._network_topology_task = None
        self._anomaly_detection_task = None
        self._discovery_processor_task: Optional[asyncio.Task] = None
        
        # Configuration
        self._health_check_interval = 60  # seconds
        self._metrics_retention_hours = 24 * 7  # 7 days
        self._agent_timeout_seconds = 300  # 5 minutes
        self._max_agent_instances = 10  # per agent type
        
        # Notification system
        self._notification_handlers: List[Callable] = []
        self._alert_thresholds: Dict[str, Dict[str, float]] = {
            "response_time": {"warning": 5.0, "critical": 10.0},
            "error_rate": {"warning": 0.1, "critical": 0.2},
            "cpu_usage": {"warning": 0.8, "critical": 0.9},
            "memory_usage": {"warning": 0.8, "critical": 0.9}
        }
        
        # Authentication and authorization
        self._agent_tokens: Dict[str, str] = {}
        self._agent_permissions: Dict[str, Set[str]] = defaultdict(set)
        self._agent_roles: Dict[str, Set[str]] = defaultdict(set)
        self._audit_log: deque = deque(maxlen=10000)
        
        # Integration flags
        self._orchestrator_integration = False
        self._monitor_integration = False
        self._monitor_service = None
    
    async def initialize(self) -> bool:
        """Initialize the agent registry."""
        if self._initialized:
            return True
            
        try:
            self.logger.info("Initializing Agent Registry service")
            
            # Initialize internal services
            self._validation_service = AgentValidation(config=ServiceConfig(name="agent_validation"))
            await self._validation_service.initialize()
            
            self._metrics_service = AgentMetrics(config=ServiceConfig(name="agent_metrics"))
            await self._metrics_service.initialize()
            
            # Initialize authentication and authorization
            self._auth_manager = AuthManager()
            
            # Initialize memory service if available
            if HAS_MEMORY_SERVICE and UnifiedMemoryService is not None:
                from ai_karen_engine.database.client import MultiTenantPostgresClient
                from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager

                self._memory_service = UnifiedMemoryService(
                    db_client=MultiTenantPostgresClient(),
                    embedding_manager=EmbeddingManager()
                )
                await self._memory_service.initialize()
            else:
                self._memory_service = None
            
            # Load persisted agent data from memory service
            await self._load_agent_data()
            
            # Initialize capability hierarchy
            self._initialize_capability_hierarchy()
            
            # Load configuration
            await self._load_configuration()
            
            # Set up discovery system
            await self._setup_discovery()
            
            # Start background tasks
            self._health_monitor_task = asyncio.create_task(self._health_monitor())
            self._cleanup_task = asyncio.create_task(self._cleanup_old_data())
            self._analytics_task = asyncio.create_task(self._analytics_processor())
            self._discovery_task = asyncio.create_task(self._agent_discovery())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
            self._network_topology_task = asyncio.create_task(self._network_topology_monitor())
            self._anomaly_detection_task = asyncio.create_task(self._anomaly_detection_monitor())
            
            # Start discovery processor task if discovery is enabled
            if self._discovery_enabled:
                self._discovery_processor_task = asyncio.create_task(self._discovery_processor())
            
            self._initialized = True
            self.logger.info("Agent registry initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize agent registry: {e}")
            return False
    
    async def _load_agent_data(self) -> None:
        """Load agent data from the memory service."""
        try:
            if self._memory_service and HAS_MEMORY_SERVICE:
                # Load agent definitions
                agents_data = await self._memory_service.retrieve("agent_registry", "agents")
                if agents_data:
                    for agent_data in agents_data:
                        agent_def = AgentDefinition(**agent_data)
                        self._agents[agent_def.agent_id] = agent_def
                
                # Load agent metadata
                metadata_data = await self._memory_service.retrieve("agent_registry", "metadata")
                if metadata_data:
                    self._agent_metadata.update(metadata_data)
                
                # Load agent health data
                health_data = await self._memory_service.retrieve("agent_registry", "health")
                if health_data:
                    self._agent_health.update(health_data)
                
                # Load capability hierarchy
                hierarchy_data = await self._memory_service.retrieve("agent_registry", "capability_hierarchy")
                if hierarchy_data:
                    for cap, parent in hierarchy_data.get("parent_child", {}).items():
                        self._capability_hierarchy.add_capability(cap, parent)
                    
                    for cap, attrs in hierarchy_data.get("attributes", {}).items():
                        self._capability_hierarchy.add_capability(cap, attributes=attrs)
                
                self.logger.info(f"Loaded data for {len(self._agents)} agents from memory service")
        except Exception as e:
            self.logger.error(f"Failed to load agent data from memory service: {e}")
    
    async def _save_agent_data(self) -> None:
        """Save agent data to the memory service."""
        try:
            if self._memory_service and HAS_MEMORY_SERVICE:
                # Save agent definitions
                agents_data = [agent.dict() for agent in self._agents.values()]
                await self._memory_service.store("agent_registry", "agents", agents_data)
                
                # Save agent metadata
                await self._memory_service.store("agent_registry", "metadata", dict(self._agent_metadata))
                
                # Save agent health data
                await self._memory_service.store("agent_registry", "health", dict(self._agent_health))
                
                # Save capability hierarchy
                hierarchy_data = {
                    "parent_child": self._capability_hierarchy._parent_child_map,
                    "attributes": self._capability_hierarchy._capability_attributes
                }
                await self._memory_service.store("agent_registry", "capability_hierarchy", hierarchy_data)
                
                self.logger.info(f"Saved data for {len(self._agents)} agents to memory service")
        except Exception as e:
            self.logger.error(f"Failed to save agent data to memory service: {e}")
    
    def _initialize_capability_hierarchy(self) -> None:
        """Initialize the capability hierarchy with default relationships."""
        # Basic capability hierarchy
        self._capability_hierarchy.add_capability("processing", attributes={"category": "core", "description": "Data processing capabilities"})
        self._capability_hierarchy.add_capability("analysis", parent="processing", attributes={"category": "core", "description": "Data analysis capabilities"})
        self._capability_hierarchy.add_capability("transformation", parent="processing", attributes={"category": "core", "description": "Data transformation capabilities"})
        
        self._capability_hierarchy.add_capability("communication", attributes={"category": "core", "description": "Communication capabilities"})
        self._capability_hierarchy.add_capability("messaging", parent="communication", attributes={"category": "core", "description": "Messaging capabilities"})
        self._capability_hierarchy.add_capability("notification", parent="communication", attributes={"category": "core", "description": "Notification capabilities"})
        
        self._capability_hierarchy.add_capability("storage", attributes={"category": "core", "description": "Data storage capabilities"})
        self._capability_hierarchy.add_capability("retrieval", parent="storage", attributes={"category": "core", "description": "Data retrieval capabilities"})
        
        self._capability_hierarchy.add_capability("ai", attributes={"category": "advanced", "description": "AI and ML capabilities"})
        self._capability_hierarchy.add_capability("nlp", parent="ai", attributes={"category": "advanced", "description": "Natural language processing capabilities"})
        self._capability_hierarchy.add_capability("vision", parent="ai", attributes={"category": "advanced", "description": "Computer vision capabilities"})
        
        self.logger.info("Initialized capability hierarchy")
    
    async def _load_configuration(self) -> None:
        """Load configuration settings for agent registry."""
        try:
            # Load discovery configuration
            config_dict = self._config.to_dict() if hasattr(self._config, 'to_dict') else {}
            self._discovery_enabled = config_dict.get("discovery_enabled", False)
            self._discovery_interval_minutes = config_dict.get("discovery_interval_minutes", 5)
            self._discovery_sources = config_dict.get("discovery_sources", [])
            self._auto_register_discovered = config_dict.get("auto_register_discovered", True)
            
            self.logger.info(f"Loaded configuration: discovery_enabled={self._discovery_enabled}, "
                           f"discovery_interval_minutes={self._discovery_interval_minutes}")
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            # Use default values if configuration loading fails
            self._discovery_enabled = False
            self._discovery_interval_minutes = 5
            self._discovery_sources = []
            self._auto_register_discovered = True
    
    async def _setup_discovery(self) -> None:
        """Set up the discovery system."""
        try:
            if not self._discovery_enabled:
                self.logger.info("Discovery is disabled, skipping setup")
                return
            
            self.logger.info("Setting up discovery system")
            
            # Initialize discovery sources
            if not self._discovery_sources:
                # Add default discovery sources if none are configured
                self._discovery_sources = [
                    {
                        "type": "network_scan",
                        "enabled": True,
                        "config": {
                            "port_range": "8000-9000",
                            "timeout": 5
                        }
                    },
                    {
                        "type": "registry_query",
                        "enabled": True,
                        "config": {
                            "endpoint": "http://localhost:8080/api/agents"
                        }
                    }
                ]
            
            # Start discovery processor task
            self._discovery_processor_task = asyncio.create_task(self._discovery_processor())
            
            self.logger.info("Discovery system setup completed")
        except Exception as e:
            self.logger.error(f"Error setting up discovery system: {e}")
    
    async def discover_agents(self, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Manually trigger agent discovery.
        
        Args:
            sources: Optional list of source types to discover from.
                     If None, discovers from all configured sources.
                     
        Returns:
            Discovery results dictionary
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            self.logger.info("Starting manual agent discovery")
            
            # Get sources to discover from
            discovery_sources = self._discovery_sources
            if sources:
                discovery_sources = [s for s in self._discovery_sources if s.get("type") in sources]
            
            if not discovery_sources:
                return {
                    "status": "error",
                    "message": "No discovery sources available",
                    "discovered_agents": []
                }
            
            # Discover agents from each source
            all_discovered_agents = {}
            
            for source in discovery_sources:
                source_type = source.get("type")
                if source.get("enabled", True):
                    discovered = await self._discover_from_source(source)
                    if discovered:
                        all_discovered_agents[source_type] = discovered
            
            # Validate discovered agents
            validated_agents = {}
            for source_type, agents in all_discovered_agents.items():
                validated_agents[source_type] = []
                for agent in agents:
                    if await self._validate_discovered_agent(agent):
                        validated_agents[source_type].append(agent)
                        
                        # Auto-register if enabled
                        if self._auto_register_discovered:
                            await self.register_agent(
                                agent_id=agent["id"],
                                agent_type=agent.get("type", "discovered"),
                                capabilities=agent.get("capabilities", []),
                                endpoint=agent.get("endpoint"),
                                metadata=agent.get("metadata", {}),
                                version=agent.get("version", "1.0.0")
                            )
            
            # Update discovered agents cache
            for source_type, agents in validated_agents.items():
                for agent in agents:
                    self._discovered_agents[agent["id"]] = {
                        "source_type": source_type,
                        "discovered_at": datetime.utcnow().isoformat(),
                        "agent_data": agent
                    }
            
            result = {
                "status": "success",
                "message": f"Discovered {sum(len(agents) for agents in validated_agents.values())} agents",
                "discovered_agents": validated_agents,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            self.logger.info(f"Manual discovery completed: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error during manual agent discovery: {e}")
            return {
                "status": "error",
                "message": str(e),
                "discovered_agents": [],
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _discovery_processor(self) -> None:
        """Background task for processing agent discovery."""
        while True:
            try:
                if not self._initialized or not self._discovery_enabled:
                    await asyncio.sleep(60)  # Check every minute if disabled
                    continue
                
                # Perform discovery from all enabled sources
                for source in self._discovery_sources:
                    if source.get("enabled", True):
                        try:
                            discovered_agents = await self._discover_from_source(source)
                            
                            if discovered_agents:
                                for agent in discovered_agents:
                                    # Validate discovered agent
                                    if await self._validate_discovered_agent(agent):
                                        # Add to discovered agents cache
                                        self._discovered_agents[agent["id"]] = {
                                            "source_type": source.get("type"),
                                            "discovered_at": datetime.utcnow().isoformat(),
                                            "agent_data": agent
                                        }
                                        
                                        # Auto-register if enabled
                                        if self._auto_register_discovered:
                                            await self.register_agent(
                                                agent_id=agent["id"],
                                                agent_type=agent.get("type", "discovered"),
                                                capabilities=agent.get("capabilities", []),
                                                endpoint=agent.get("endpoint"),
                                                metadata=agent.get("metadata", {}),
                                                version=agent.get("version", "1.0.0")
                                            )
                        except Exception as e:
                            self.logger.error(f"Error discovering from source {source.get('type')}: {e}")
                
                # Sleep until next discovery cycle
                await asyncio.sleep(self._discovery_interval_minutes * 60)
                
            except Exception as e:
                self.logger.error(f"Error in discovery processor: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def _discover_from_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Discover agents from a specific source.
        
        Args:
            source: Source configuration dictionary
            
        Returns:
            List of discovered agent dictionaries
        """
        source_type = source.get("type")
        config = source.get("config", {})
        
        try:
            if source_type == "network_scan":
                return await self._discover_from_network_scan(config)
            elif source_type == "registry_query":
                return await self._discover_from_registry_query(config)
            else:
                self.logger.warning(f"Unknown discovery source type: {source_type}")
                return []
        except Exception as e:
            self.logger.error(f"Error discovering from source {source_type}: {e}")
            return []
    
    async def _discover_from_network_scan(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Discover agents through network scanning.
        
        Args:
            config: Network scan configuration
            
        Returns:
            List of discovered agent dictionaries
        """
        # In a real implementation, this would perform actual network scanning
        # For now, we'll return an empty list as a placeholder
        self.logger.info("Network scan discovery (placeholder implementation)")
        return []
    
    async def _discover_from_registry_query(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Discover agents through registry queries.
        
        Args:
            config: Registry query configuration
            
        Returns:
            List of discovered agent dictionaries
        """
        # In a real implementation, this would query external registries
        # For now, we'll return an empty list as a placeholder
        self.logger.info("Registry query discovery (placeholder implementation)")
        return []
    
    async def _validate_discovered_agent(self, agent: Dict[str, Any]) -> bool:
        """
        Validate a discovered agent before registration.
        
        Args:
            agent: Discovered agent dictionary
            
        Returns:
            True if agent is valid, False otherwise
        """
        try:
            # Check required fields
            required_fields = ["id", "type"]
            for field in required_fields:
                if field not in agent:
                    self.logger.warning(f"Discovered agent missing required field: {field}")
                    return False
            
            # Check if agent already exists
            if agent["id"] in self._agents:
                self.logger.debug(f"Agent {agent['id']} already registered")
                return False
            
            # Validate agent format
            if not isinstance(agent["id"], str) or not agent["id"]:
                self.logger.warning(f"Invalid agent ID: {agent['id']}")
                return False
            
            if not isinstance(agent.get("capabilities", []), list):
                self.logger.warning(f"Invalid capabilities for agent {agent['id']}")
                return False
            
            # Additional validation can be added here
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating discovered agent: {e}")
            return False
    
    # Dynamic Agent Discovery Methods
    
    async def start_agent_discovery(self) -> bool:
        """
        Start the dynamic agent discovery process.
        
        Returns:
            True if discovery was started successfully, False otherwise
        """
        if self._discovery_active:
            self.logger.warning("Agent discovery is already active")
            return True
        
        try:
            self._discovery_active = True
            self.logger.info("Started dynamic agent discovery")
            
            # Trigger discovery event
            await self._trigger_event(AgentLifecycleEvent.DISCOVERED, {
                "action": "discovery_started",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to start agent discovery: {e}")
            self._discovery_active = False
            return False
    
    async def stop_agent_discovery(self) -> bool:
        """
        Stop the dynamic agent discovery process.
        
        Returns:
            True if discovery was stopped successfully, False otherwise
        """
        if not self._discovery_active:
            self.logger.warning("Agent discovery is not active")
            return True
        
        try:
            self._discovery_active = False
            self.logger.info("Stopped dynamic agent discovery")
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop agent discovery: {e}")
            return False
    
    async def register_agent_heartbeat(self, agent_id: str, endpoint: str, status: AgentHealthStatus,
                                      capabilities: Optional[List[str]] = None, metadata: Optional[Dict[str, Any]] = None,
                                      resource_usage: Optional[Dict[str, float]] = None) -> bool:
        """
        Register a heartbeat from an agent.
        
        Args:
            agent_id: ID of the agent
            endpoint: Agent endpoint
            status: Current health status
            capabilities: List of agent capabilities
            metadata: Agent metadata
            resource_usage: Resource usage metrics
            
        Returns:
            True if heartbeat was registered successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            heartbeat = AgentHeartbeat(
                agent_id=agent_id,
                timestamp=datetime.utcnow(),
                status=status,
                endpoint=endpoint,
                capabilities=capabilities or [],
                metadata=metadata or {},
                resource_usage=resource_usage or {}
            )
            
            async with self._lock:
                # Store heartbeat
                self._agent_heartbeats[agent_id] = heartbeat
                
                # Update agent last seen time
                if agent_id in self._agent_instances:
                    self._agent_instances[agent_id]["last_seen"] = heartbeat.timestamp
                
                # Update resource usage
                if resource_usage and agent_id in self._agent_instances:
                    self._agent_instances[agent_id]["resources"] = resource_usage
                    # Add to history for anomaly detection
                    self._resource_usage_history[agent_id].append({
                        "timestamp": heartbeat.timestamp.isoformat(),
                        "resources": resource_usage.copy()
                    })
                    # Keep only recent history
                    if len(self._resource_usage_history[agent_id]) > 100:
                        self._resource_usage_history[agent_id] = self._resource_usage_history[agent_id][-100:]
                
                # Update agent health status
                await self.update_agent_health(agent_id, status, {
                    "heartbeat": True,
                    "resource_usage": resource_usage
                })
                
                # If agent is not registered, register it automatically
                if agent_id not in self._agents:
                    await self.register_agent(
                        agent_id=agent_id,
                        agent_type=metadata.get("agent_type", "discovered"),
                        capabilities=capabilities or [],
                        endpoint=endpoint,
                        metadata=metadata or {},
                        version=metadata.get("version", "1.0.0")
                    )
                    # Trigger discovery event
                    await self._trigger_event(AgentLifecycleEvent.DISCOVERED, {
                        "agent_id": agent_id,
                        "endpoint": endpoint,
                        "capabilities": capabilities or [],
                        "metadata": metadata or {}
                    })
                else:
                    # Trigger heartbeat event
                    await self._trigger_event(AgentLifecycleEvent.HEARTBEAT, {
                        "agent_id": agent_id,
                        "status": status.value,
                        "timestamp": heartbeat.timestamp.isoformat()
                    })
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to register heartbeat for agent {agent_id}: {e}")
            return False
    
    async def get_agent_heartbeat(self, agent_id: str) -> Optional[AgentHeartbeat]:
        """
        Get the latest heartbeat for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent heartbeat if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return self._agent_heartbeats.get(agent_id)
    
    async def get_all_heartbeats(self) -> Dict[str, AgentHeartbeat]:
        """
        Get all agent heartbeats.
        
        Returns:
            Dictionary of agent heartbeats by agent ID
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return self._agent_heartbeats.copy()
    
    async def _agent_discovery(self) -> None:
        """Background task for agent discovery."""
        while True:
            try:
                if not self._initialized or not self._discovery_active:
                    await asyncio.sleep(1)
                    continue
                
                # Perform agent discovery
                # This is where we would implement network scanning or other discovery mechanisms
                # For now, we'll just check existing heartbeats
                
                async with self._lock:
                    # Check for stale heartbeats
                    now = datetime.utcnow()
                    stale_agents = []
                    
                    for agent_id, heartbeat in self._agent_heartbeats.items():
                        if (now - heartbeat.timestamp).total_seconds() > self._agent_timeout_seconds:
                            stale_agents.append(agent_id)
                    
                    # Handle stale agents
                    for agent_id in stale_agents:
                        self.logger.warning(f"Agent {agent_id} heartbeat is stale")
                        await self._handle_stale_agent(agent_id)
                
                # Sleep until next discovery cycle
                await asyncio.sleep(self._discovery_interval)
                
            except Exception as e:
                self.logger.error(f"Error in agent discovery: {e}")
                await asyncio.sleep(self._discovery_interval)
    
    async def _heartbeat_monitor(self) -> None:
        """Background task for monitoring agent heartbeats."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Check all agent heartbeats
                async with self._lock:
                    now = datetime.utcnow()
                    agent_ids = list(self._agents.keys())
                
                for agent_id in agent_ids:
                    try:
                        # Check if agent has a recent heartbeat
                        heartbeat = self._agent_heartbeats.get(agent_id)
                        if heartbeat:
                            time_since_heartbeat = (now - heartbeat.timestamp).total_seconds()
                            if time_since_heartbeat > self._heartbeat_interval * 2:
                                # Agent missed heartbeats
                                await self._handle_missed_heartbeat(agent_id, time_since_heartbeat)
                        else:
                            # Agent has no heartbeat record
                            if agent_id in self._agent_instances:
                                last_seen = self._agent_instances[agent_id]["last_seen"]
                                time_since_seen = (now - last_seen).total_seconds()
                                if time_since_seen > self._agent_timeout_seconds:
                                    await self._handle_stale_agent(agent_id)
                    except Exception as e:
                        self.logger.error(f"Error checking heartbeat for agent {agent_id}: {e}")
                
                # Sleep until next check
                await asyncio.sleep(self._heartbeat_interval)
                
            except Exception as e:
                self.logger.error(f"Error in heartbeat monitor: {e}")
                await asyncio.sleep(self._heartbeat_interval)
    
    async def _handle_stale_agent(self, agent_id: str) -> None:
        """Handle a stale agent."""
        try:
            # Update agent health status
            await self.update_agent_health(agent_id, AgentHealthStatus.UNKNOWN, {
                "reason": "stale_heartbeat",
                "last_heartbeat": self._agent_heartbeats.get(agent_id).timestamp.isoformat() if agent_id in self._agent_heartbeats else None
            })
            
            # Attempt to reconnect
            if await self._attempt_agent_reconnection(agent_id):
                self.logger.info(f"Successfully reconnected to agent {agent_id}")
            else:
                self.logger.warning(f"Failed to reconnect to agent {agent_id}")
        except Exception as e:
            self.logger.error(f"Error handling stale agent {agent_id}: {e}")
    
    async def _handle_missed_heartbeat(self, agent_id: str, time_since_heartbeat: float) -> None:
        """Handle a missed heartbeat from an agent."""
        try:
            # Update agent health status
            await self.update_agent_health(agent_id, AgentHealthStatus.UNKNOWN, {
                "reason": "missed_heartbeat",
                "time_since_heartbeat": time_since_heartbeat
            })
            
            # Attempt to reconnect
            if await self._attempt_agent_reconnection(agent_id):
                self.logger.info(f"Successfully reconnected to agent {agent_id} after missed heartbeat")
            else:
                self.logger.warning(f"Failed to reconnect to agent {agent_id} after missed heartbeat")
        except Exception as e:
            self.logger.error(f"Error handling missed heartbeat for agent {agent_id}: {e}")
    
    async def _attempt_agent_reconnection(self, agent_id: str) -> bool:
        """
        Attempt to reconnect to an agent.
        
        Args:
            agent_id: ID of the agent to reconnect to
            
        Returns:
            True if reconnection was successful, False otherwise
        """
        if not self._initialized:
            return False
        
        try:
            # Get agent information
            agent_info = self._agents.get(agent_id)
            if not agent_info:
                return False
            
            # Get agent endpoint
            endpoint = agent_info.endpoint
            if not endpoint:
                self.logger.warning(f"No endpoint available for agent {agent_id}")
                return False
            
            # Attempt reconnection
            for attempt in range(self._reconnection_attempts):
                try:
                    # In a real implementation, this would make an actual connection attempt
                    # For now, we'll simulate a successful reconnection
                    await asyncio.sleep(self._reconnection_delay)
                    
                    # If we get here, reconnection was successful
                    # Update agent health status
                    await self.update_agent_health(agent_id, AgentHealthStatus.HEALTHY, {
                        "reason": "reconnected",
                        "attempts": attempt + 1
                    })
                    
                    # Trigger reconnection event
                    await self._trigger_event(AgentLifecycleEvent.RECONNECTED, {
                        "agent_id": agent_id,
                        "attempts": attempt + 1
                    })
                    
                    return True
                except Exception as e:
                    self.logger.warning(f"Reconnection attempt {attempt + 1} for agent {agent_id} failed: {e}")
            
            # All reconnection attempts failed
            await self.update_agent_health(agent_id, AgentHealthStatus.UNHEALTHY, {
                "reason": "reconnection_failed",
                "attempts": self._reconnection_attempts
            })
            
            return False
        except Exception as e:
            self.logger.error(f"Error attempting to reconnect to agent {agent_id}: {e}")
            return False
    
    async def update_network_topology(self, agent_id: str, neighbors: List[str],
                                    connection_quality: Optional[Dict[str, float]] = None) -> bool:
        """
        Update network topology information for an agent.
        
        Args:
            agent_id: ID of the agent
            neighbors: List of neighboring agent IDs
            connection_quality: Quality metrics to neighbors
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            async with self._lock:
                # Create or update topology info
                if agent_id not in self._network_topology:
                    self._network_topology[agent_id] = AgentNetworkTopology(agent_id=agent_id)
                
                topology = self._network_topology[agent_id]
                topology.neighbors = set(neighbors)
                
                if connection_quality:
                    topology.connection_quality = connection_quality
                
                # Update network graph
                self._network_graph.add_node(agent_id)
                for neighbor in neighbors:
                    self._network_graph.add_edge(agent_id, neighbor)
                
                # Calculate network distances
                for other_id in self._network_graph.nodes():
                    if other_id != agent_id and isinstance(other_id, str) and nx.has_path(self._network_graph, agent_id, other_id):
                        try:
                            path_length = nx.shortest_path_length(
                                self._network_graph, agent_id, other_id
                            )
                            if isinstance(path_length, int):
                                topology.network_distance[other_id] = path_length
                        except nx.NetworkXNoPath:
                            # No path exists between nodes
                            pass
                
                # Calculate network position using a simple layout algorithm
                if self._network_graph.number_of_nodes() > 1:
                    pos = nx.spring_layout(self._network_graph)
                    if agent_id in pos:
                        topology.network_position = pos[agent_id]
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to update network topology for agent {agent_id}: {e}")
            return False
    
    async def get_network_topology(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get network topology information.
        
        Args:
            agent_id: Optional agent ID to get topology for specific agent
            
        Returns:
            Network topology information
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id:
                topology = self._network_topology.get(agent_id)
                if topology:
                    return {
                        "agent_id": topology.agent_id,
                        "neighbors": list(topology.neighbors),
                        "network_distance": topology.network_distance,
                        "network_position": topology.network_position,
                        "connection_quality": topology.connection_quality
                    }
                return {}
            else:
                # Return all topology information
                result = {}
                for agent_id, topology in self._network_topology.items():
                    result[agent_id] = {
                        "neighbors": list(topology.neighbors),
                        "network_distance": topology.network_distance,
                        "network_position": topology.network_position,
                        "connection_quality": topology.connection_quality
                    }
                return result
    
    async def _network_topology_monitor(self) -> None:
        """Background task for monitoring network topology."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Update network topology based on agent dependencies
                async with self._lock:
                    # Build network graph from agent dependencies
                    self._network_graph.clear()
                    
                    for agent_id, dependencies in self._agent_dependencies.items():
                        if agent_id in self._agents:  # Only include active agents
                            self._network_graph.add_node(agent_id)
                            for dep_id in dependencies:
                                if dep_id in self._agents:  # Only include active dependencies
                                    self._network_graph.add_node(dep_id)
                                    self._network_graph.add_edge(agent_id, dep_id)
                    
                    # Update topology for all agents
                    for agent_id in self._network_graph.nodes():
                        if isinstance(agent_id, str):
                            neighbors = list(self._network_graph.neighbors(agent_id))
                            await self.update_network_topology(agent_id, neighbors)
                
                # Sleep until next update
                await asyncio.sleep(60)  # Update every minute
                
            except Exception as e:
                self.logger.error(f"Error in network topology monitor: {e}")
                await asyncio.sleep(60)
    
    async def _anomaly_detection_monitor(self) -> None:
        """Background task for detecting anomalies in agent behavior."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Check for anomalies in agent behavior
                async with self._lock:
                    for agent_id, history in self._resource_usage_history.items():
                        if len(history) < 10:  # Need enough data points
                            continue
                        
                        # Check for anomalies in resource usage
                        cpu_usage = [point["resources"].get("cpu", 0) for point in history[-10:]]
                        memory_usage = [point["resources"].get("memory", 0) for point in history[-10:]]
                        
                        # Calculate mean and standard deviation
                        cpu_mean = np.mean(cpu_usage)
                        cpu_std = np.std(cpu_usage)
                        memory_mean = np.mean(memory_usage)
                        memory_std = np.std(memory_usage)
                        
                        # Check for anomalies (values beyond threshold standard deviations)
                        current_cpu = cpu_usage[-1]
                        current_memory = memory_usage[-1]
                        
                        cpu_anomaly = abs(current_cpu - cpu_mean) > (self._anomaly_detection_threshold * cpu_std)
                        memory_anomaly = abs(current_memory - memory_mean) > (self._anomaly_detection_threshold * memory_std)
                        
                        if cpu_anomaly or memory_anomaly:
                            # Anomaly detected
                            anomaly_details = {
                                "cpu_usage": {
                                    "current": current_cpu,
                                    "mean": cpu_mean,
                                    "std": cpu_std,
                                    "anomaly": cpu_anomaly
                                },
                                "memory_usage": {
                                    "current": current_memory,
                                    "mean": memory_mean,
                                    "std": memory_std,
                                    "anomaly": memory_anomaly
                                }
                            }
                            
                            self.logger.warning(f"Resource usage anomaly detected for agent {agent_id}: {anomaly_details}")
                            
                            # Update agent health status if anomaly is severe
                            if current_cpu > 0.9 or current_memory > 0.9:
                                await self.update_agent_health(agent_id, AgentHealthStatus.DEGRADED, {
                                    "reason": "resource_anomaly",
                                    "details": anomaly_details
                                })
                
                # Sleep until next check
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Error in anomaly detection monitor: {e}")
                await asyncio.sleep(300)
    
    # Agent Registration and Deregistration
    
    async def register_agent(
        self, 
        agent_id: str, 
        agent_type: str, 
        capabilities: List[Union[str, AgentCapability]],
        endpoint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        dependencies: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        categories: Optional[List[str]] = None
    ) -> bool:
        """
        Register a new agent in the registry.
        
        Args:
            agent_id: Unique identifier for the agent
            agent_type: Type/category of the agent
            capabilities: List of capabilities the agent provides
            endpoint: Optional endpoint URL for the agent
            metadata: Additional metadata about the agent
            version: Version of the agent
            dependencies: List of agent IDs this agent depends on
            tags: List of tags for categorization
            categories: List of categories the agent belongs to
            
        Returns:
            True if registration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        # Validate agent configuration
        if self._validation_service:
            config = {
                "agent_id": agent_id,
                "name": metadata.get("name", agent_id) if metadata else agent_id,
                "agent_type": agent_type,
                "capabilities": capabilities,
                "version": version
            }
            is_valid, errors = await self._validation_service.validate_agent_configuration(config)
            if not is_valid:
                self.logger.error(f"Agent configuration validation failed: {errors}")
                return False
        
        async with self._lock:
            # Check if agent already exists
            if agent_id in self._agents:
                self.logger.warning(f"Agent {agent_id} already registered, updating registration")
                await self._trigger_event(AgentLifecycleEvent.UPDATED, {"agent_id": agent_id})
            
            # Convert string capabilities to AgentCapability objects if needed
            agent_capabilities = []
            for cap in capabilities:
                if isinstance(cap, str):
                    agent_capabilities.append(AgentCapability(name=cap))
                else:
                    agent_capabilities.append(cap)
            
            # Create agent definition
            agent_def = AgentDefinition(
                agent_id=agent_id,
                name=metadata.get("name", agent_id) if metadata else agent_id,
                description=metadata.get("description", "") if metadata else "",
                agent_type=agent_type,
                version=version,
                capabilities=agent_capabilities,
                endpoint=endpoint,
                status=AgentStatus.READY,
                metadata=metadata or {},
                config={}
            )
            
            # Store agent
            self._agents[agent_id] = agent_def
            
            # Initialize agent instance data
            self._agent_instances[agent_id] = {
                "status": AgentStatus.READY,
                "resources": {
                    "cpu": 0.0,
                    "memory": 0.0,
                    "active_tasks": 0
                },
                "endpoint": endpoint,
                "last_seen": datetime.utcnow()
            }
            
            # Store metadata
            self._agent_metadata[agent_id] = metadata or {}
            
            # Initialize health data
            self._agent_health[agent_id] = {
                "status": AgentHealthStatus.HEALTHY,
                "last_check": datetime.utcnow(),
                "consecutive_failures": 0
            }
            
            # Store version
            self._agent_versions[agent_id] = {
                "current": version,
                "compatible": ["1.0.0"]  # Default compatibility
            }
            
            # Update capability index
            for cap in agent_capabilities:
                self._capability_index[cap.name].add(agent_id)
            
            # Update semantic index
            if metadata:
                description = metadata.get("description", "")
                keywords = metadata.get("keywords", [])
                for keyword in keywords:
                    self._semantic_index[keyword.lower()].append(agent_id)
            
            # Update category index
            if categories:
                for category in categories:
                    self._category_index[category.lower()].add(agent_id)
            
            # Update tag index
            if tags:
                for tag in tags:
                    self._tag_index[tag.lower()].add(agent_id)
            
            # Update dependencies
            if dependencies:
                self._agent_dependencies[agent_id] = set(dependencies)
                for dep_id in dependencies:
                    if dep_id in self._agent_relationships:
                        if agent_id not in self._agent_relationships[dep_id]["used_by"]:
                            self._agent_relationships[dep_id]["used_by"].append(agent_id)
                    
                    if "depends_on" not in self._agent_relationships[agent_id]:
                        self._agent_relationships[agent_id]["depends_on"] = []
                    if dep_id not in self._agent_relationships[agent_id]["depends_on"]:
                        self._agent_relationships[agent_id]["depends_on"].append(dep_id)
            
            # Initialize performance tracking
            self._agent_performance[agent_id] = {
                "response_times": deque(maxlen=100),
                "success_rates": deque(maxlen=100),
                "error_counts": defaultdict(int),
                "last_activity": datetime.utcnow(),
                "uptime_start": datetime.utcnow(),
                "downtime_periods": []
            }
            
            # Initialize configuration
            self._agent_configs[agent_id] = metadata.get("config", {})
            self._config_history[agent_id].append({
                "timestamp": datetime.utcnow().isoformat(),
                "config": metadata.get("config", {}),
                "changed_by": "registration"
            })
            
            # Trigger registration event
            await self._trigger_event(AgentLifecycleEvent.REGISTERED, {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "capabilities": [cap.name for cap in agent_capabilities],
                "metadata": metadata or {}
            })
            
            self.logger.info(f"Agent {agent_id} registered successfully")
            
            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_agent_execution_time(agent_id, 0.0)
            
            # Persist agent data
            await self._enhanced_save_agent_data()
            
            return True
    
    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Unregister an agent from the registry.
        
        Args:
            agent_id: Unique identifier of the agent to unregister
            
        Returns:
            True if unregistration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Get agent info before removal
            agent_info = self._agents[agent_id]
            
            # Remove from agents
            del self._agents[agent_id]
            
            # Remove from instances
            if agent_id in self._agent_instances:
                del self._agent_instances[agent_id]
            
            # Remove from metadata
            if agent_id in self._agent_metadata:
                del self._agent_metadata[agent_id]
            
            # Remove from health
            if agent_id in self._agent_health:
                del self._agent_health[agent_id]
            
            # Remove from versions
            if agent_id in self._agent_versions:
                del self._agent_versions[agent_id]
            
            # Remove from capability index
            for cap_name, agent_ids in list(self._capability_index.items()):
                if agent_id in agent_ids:
                    agent_ids.remove(agent_id)
                    if not agent_ids:
                        del self._capability_index[cap_name]
            
            # Remove from semantic index
            for keyword, agent_ids in list(self._semantic_index.items()):
                if agent_id in agent_ids:
                    agent_ids.remove(agent_id)
                    if not agent_ids:
                        del self._semantic_index[keyword]
            
            # Remove from category index
            for category, agent_ids in list(self._category_index.items()):
                if agent_id in agent_ids:
                    agent_ids.remove(agent_id)
                    if not agent_ids:
                        del self._category_index[category]
            
            # Remove from tag index
            for tag, agent_ids in list(self._tag_index.items()):
                if agent_id in agent_ids:
                    agent_ids.remove(agent_id)
                    if not agent_ids:
                        del self._tag_index[tag]
            
            # Remove from dependencies
            if agent_id in self._agent_dependencies:
                del self._agent_dependencies[agent_id]
            
            # Remove from relationships
            if agent_id in self._agent_relationships:
                del self._agent_relationships[agent_id]
            
            # Remove from performance tracking
            if agent_id in self._agent_performance:
                del self._agent_performance[agent_id]
            
            # Remove from configuration
            if agent_id in self._agent_configs:
                del self._agent_configs[agent_id]
            
            # Remove from config history
            if agent_id in self._config_history:
                del self._config_history[agent_id]
            
            # Update relationships for dependent agents
            for rel_agent_id, relationships in self._agent_relationships.items():
                if "depends_on" in relationships and agent_id in relationships["depends_on"]:
                    relationships["depends_on"].remove(agent_id)
                if "used_by" in relationships and agent_id in relationships["used_by"]:
                    relationships["used_by"].remove(agent_id)
                if "similar" in relationships and agent_id in relationships["similar"]:
                    relationships["similar"].remove(agent_id)
                if "complementary" in relationships and agent_id in relationships["complementary"]:
                    relationships["complementary"].remove(agent_id)
            
            # Trigger deregistration event
            await self._trigger_event(AgentLifecycleEvent.DEREGISTERED, {
                "agent_id": agent_id,
                "agent_type": agent_info.agent_type,
                "capabilities": [cap.name for cap in agent_info.capabilities],
                "metadata": agent_info.metadata
            })
            
            self.logger.info(f"Agent {agent_id} unregistered successfully")
            return True
    
    # Agent Capability Indexing and Discovery
    
    async def create_capability_embedding(self, capability: str, description: Optional[str] = None) -> CapabilityEmbedding:
        """
        Create a vector embedding for a capability.
        
        Args:
            capability: Name of the capability
            description: Optional description of the capability
            
        Returns:
            Capability embedding object
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Initialize embedding model if needed
            if self._embedding_model is None:
                # For now, use a simple random embedding
                # In a real implementation, this would use a proper embedding model
                embedding = np.random.normal(0, 1, self._embedding_dimension)
                # Normalize the embedding
                embedding = embedding / np.linalg.norm(embedding)
            else:
                # Use embedding model to create an embedding
                text = f"{capability}: {description or ''}"
                embedding = self._embedding_model.encode(text)
            
            # Create capability embedding
            cap_embedding = CapabilityEmbedding(
                capability=capability,
                embedding=embedding,
                version="1.0"
            )
            
            # Store the embedding
            self._capability_embeddings[capability] = cap_embedding
            
            return cap_embedding
        except Exception as e:
            self.logger.error(f"Failed to create embedding for capability {capability}: {e}")
            # Return a random embedding as fallback
            embedding = np.random.normal(0, 1, self._embedding_dimension)
            embedding = embedding / np.linalg.norm(embedding)
            return CapabilityEmbedding(
                capability=capability,
                embedding=embedding,
                version="1.0"
            )
    
    async def find_similar_capabilities(self, capability: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Find capabilities similar to the given capability.
        
        Args:
            capability: Name of the capability
            limit: Maximum number of similar capabilities to return
            
        Returns:
            List of tuples (capability_name, similarity_score)
        """
        if not self._initialized:
            await self.initialize()
        
        if capability not in self._capability_embeddings:
            # Create embedding for the capability if it doesn't exist
            await self.create_capability_embedding(capability)
        
        target_embedding = self._capability_embeddings[capability].embedding
        
        # Calculate similarity with all other capabilities
        similarities = []
        for cap_name, cap_embedding in self._capability_embeddings.items():
            if cap_name != capability:
                # Calculate cosine similarity
                similarity = np.dot(target_embedding, cap_embedding.embedding) / (
                    np.linalg.norm(target_embedding) * np.linalg.norm(cap_embedding.embedding)
                )
                similarities.append((cap_name, float(similarity)))
        
        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]
    
    async def semantic_search_capabilities(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Search for capabilities using semantic matching.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of tuples (capability_name, similarity_score)
        """
        if not self._initialized:
            await self.initialize()
        
        # Create embedding for the query
        query_embedding = await self.create_capability_embedding(f"query_{uuid4()}", query)
        
        # Calculate similarity with all capabilities
        similarities = []
        for cap_name, cap_embedding in self._capability_embeddings.items():
            # Calculate cosine similarity
            similarity = np.dot(query_embedding.embedding, cap_embedding.embedding) / (
                np.linalg.norm(query_embedding.embedding) * np.linalg.norm(cap_embedding.embedding)
            )
            similarities.append((cap_name, float(similarity)))
        
        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]
    
    async def find_agents_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """
        Find agents that have a specific capability.
        
        Args:
            capability: Capability to search for
            
        Returns:
            List of agents with the specified capability
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            agent_ids = self._capability_index.get(capability, set())
            return [await self._get_agent_info(agent_id) for agent_id in agent_ids]
    
    async def find_agents_by_capabilities(self, capabilities: List[str], match_all: bool = True) -> List[Dict[str, Any]]:
        """
        Find agents that have multiple capabilities.
        
        Args:
            capabilities: List of capabilities to search for
            match_all: If True, agents must have all capabilities; if False, any capability suffices
            
        Returns:
            List of agents with the specified capabilities
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if match_all:
                # Find agents that have all specified capabilities
                agent_sets = [self._capability_index.get(cap, set()) for cap in capabilities]
                if not agent_sets:
                    return []
                
                # Find intersection of all sets
                common_agent_ids = set.intersection(*agent_sets)
                return [await self._get_agent_info(agent_id) for agent_id in common_agent_ids]
            else:
                # Find agents that have any of the specified capabilities
                agent_ids = set()
                for cap in capabilities:
                    agent_ids.update(self._capability_index.get(cap, set()))
                
                return [await self._get_agent_info(agent_id) for agent_id in agent_ids]
    
    async def semantic_search_agents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for agents using semantic matching.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of agents matching the query, sorted by relevance
        """
        if not self._initialized:
            await self.initialize()
        
        # Simple keyword-based semantic search
        # In a real implementation, this would use embeddings and vector similarity
        query_lower = query.lower()
        query_terms = query_lower.split()
        
        async with self._lock:
            # Score agents based on keyword matches
            agent_scores = defaultdict(float)
            
            for term in query_terms:
                # Check direct keyword matches
                if term in self._semantic_index:
                    for agent_id in self._semantic_index[term]:
                        agent_scores[agent_id] += 1.0
                
                # Check partial matches in capability names
                for cap_name, agent_ids in self._capability_index.items():
                    if term in cap_name.lower():
                        for agent_id in agent_ids:
                            agent_scores[agent_id] += 0.5
                
                # Check partial matches in agent types
                for agent_id, agent_def in self._agents.items():
                    if term in agent_def.agent_type.lower():
                        agent_scores[agent_id] += 0.3
                
                # Check partial matches in agent names
                for agent_id, agent_def in self._agents.items():
                    if term in agent_def.name.lower():
                        agent_scores[agent_id] += 0.3
            
            # Sort by score and return top results
            sorted_agents = sorted(agent_scores.items(), key=lambda x: x[1], reverse=True)
            result_agent_ids = [agent_id for agent_id, score in sorted_agents[:limit]]
            
            return [await self._get_agent_info(agent_id) for agent_id in result_agent_ids]
    
    async def add_capability_to_hierarchy(self, capability: str, parent: Optional[str] = None,
                                        attributes: Optional[Dict[str, Any]] = None) -> bool:
        """
        Add a capability to the hierarchy.
        
        Args:
            capability: Name of the capability
            parent: Optional parent capability
            attributes: Optional capability attributes
            
        Returns:
            True if successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            self._capability_hierarchy.add_capability(capability, parent, attributes)
            
            # Create embedding for the capability
            description = attributes.get("description", "") if attributes else ""
            await self.create_capability_embedding(capability, description)
            
            # Trigger capability broadcast event
            await self._trigger_event(AgentLifecycleEvent.CAPABILITY_BROADCAST, {
                "capability": capability,
                "parent": parent,
                "attributes": attributes or {}
            })
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to add capability {capability} to hierarchy: {e}")
            return False
    
    async def get_capability_children(self, capability: str) -> Set[str]:
        """
        Get all child capabilities of a given capability.
        
        Args:
            capability: Name of the capability
            
        Returns:
            Set of child capability names
        """
        if not self._initialized:
            await self.initialize()
        
        return self._capability_hierarchy.get_children(capability)
    
    async def get_capability_parent(self, capability: str) -> Optional[str]:
        """
        Get the parent of a capability.
        
        Args:
            capability: Name of the capability
            
        Returns:
            Parent capability name if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        return self._capability_hierarchy.get_parent(capability)
    
    async def get_capability_hierarchy(self, capability: str, include_descendants: bool = True) -> Dict[str, Any]:
        """
        Get hierarchy information for a capability.
        
        Args:
            capability: Name of the capability
            include_descendants: Whether to include all descendants
            
        Returns:
            Hierarchy information
        """
        if not self._initialized:
            await self.initialize()
        
        parent = await self.get_capability_parent(capability)
        children = await self.get_capability_children(capability)
        attributes = self._capability_hierarchy.get_attributes(capability)
        
        result = {
            "capability": capability,
            "parent": parent,
            "children": list(children) if children else [],
            "attributes": attributes
        }
        
        if include_descendants:
            descendants = set()
            for child in children:
                descendants.update(self._capability_hierarchy.get_all_descendants(child))
            result["descendants"] = list(descendants)
        
        return result
    
    async def find_agents_by_capability_hierarchy(self, capability: str, include_hierarchy: bool = True) -> List[Dict[str, Any]]:
        """
        Find agents that have a capability or its hierarchical descendants.
        
        Args:
            capability: Name of the capability
            include_hierarchy: Whether to include agents with descendant capabilities
            
        Returns:
            List of agents with the specified capability or its descendants
        """
        if not self._initialized:
            await self.initialize()
        
        capabilities_to_check = [capability]
        
        if include_hierarchy:
            # Add all descendant capabilities
            descendants = self._capability_hierarchy.get_all_descendants(capability)
            capabilities_to_check.extend(descendants)
        
        # Find agents with any of the capabilities
        agent_ids = set()
        for cap in capabilities_to_check:
            agent_ids.update(self._capability_index.get(cap, set()))
        
        return [await self._get_agent_info(agent_id) for agent_id in agent_ids]
    
    async def find_agents_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Find agents that belong to a specific category.
        
        Args:
            category: Category to search for
            
        Returns:
            List of agents in the specified category
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            agent_ids = self._category_index.get(category.lower(), set())
            return [await self._get_agent_info(agent_id) for agent_id in agent_ids]
    
    async def find_agents_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """
        Find agents that have a specific tag.
        
        Args:
            tag: Tag to search for
            
        Returns:
            List of agents with the specified tag
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            agent_ids = self._tag_index.get(tag.lower(), set())
            return [await self._get_agent_info(agent_id) for agent_id in agent_ids]
    
    async def recommend_agents(self, task_type: str, context: Optional[Dict[str, Any]] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Recommend agents for a specific task type.
        
        Args:
            task_type: Type of task to find agents for
            context: Optional context for recommendation
            limit: Maximum number of recommendations
            
        Returns:
            List of recommended agents with scores
        """
        if not self._initialized:
            await self.initialize()
        
        # Enhanced recommendation based on capability matching, embeddings, and performance
        async with self._lock:
            agent_scores = defaultdict(float)
            
            # Get semantic search results for the task type
            similar_capabilities = await self.semantic_search_capabilities(task_type, limit=20)
            
            # Create a capability relevance map
            capability_relevance = {cap: score for cap, score in similar_capabilities}
            
            # Score agents based on capability relevance and performance
            for agent_id, agent_def in self._agents.items():
                capability_score = 0
                
                # Check each capability against the relevant capabilities
                for cap in agent_def.capabilities:
                    cap_name = cap.name
                    
                    # Direct match with semantic search results
                    if cap_name in capability_relevance:
                        capability_score += capability_relevance[cap_name] * 2.0
                    
                    # Check capability hierarchy
                    parent = await self.get_capability_parent(cap_name)
                    if parent and parent in capability_relevance:
                        # Inherit some score from parent
                        capability_score += capability_relevance[parent] * 1.5
                    
                    # Check if any children are in the relevant capabilities
                    children = await self.get_capability_children(cap_name)
                    for child in children:
                        if child in capability_relevance:
                            capability_score += capability_relevance[child] * 1.2
                
                if capability_score > 0:
                    # Base score from capability relevance
                    agent_scores[agent_id] += capability_score
                    
                    # Boost score based on performance metrics
                    if agent_id in self._agent_performance:
                        perf = self._agent_performance[agent_id]
                        
                        # Response time score (lower is better)
                        if perf["response_times"]:
                            avg_response_time = sum(perf["response_times"]) / len(perf["response_times"])
                            response_time_score = 5.0 / max(avg_response_time, 0.1)
                            agent_scores[agent_id] += response_time_score
                        
                        # Success rate score (higher is better)
                        if perf["success_rates"]:
                            avg_success_rate = sum(perf["success_rates"]) / len(perf["success_rates"])
                            success_rate_score = avg_success_rate * 5.0
                            agent_scores[agent_id] += success_rate_score
                        
                        # Uptime bonus
                        if perf["uptime_start"]:
                            uptime = (datetime.utcnow() - perf["uptime_start"]).total_seconds()
                            if uptime > 86400:  # More than a day
                                agent_scores[agent_id] += 1.0
                    
                    # Context-based scoring if context is provided
                    if context:
                        # Check for context-specific capabilities
                        context_caps = context.get("required_capabilities", [])
                        for context_cap in context_caps:
                            if context_cap in [cap.name for cap in agent_def.capabilities]:
                                agent_scores[agent_id] += 3.0
                        
                        # Check for preferred agent types
                        preferred_types = context.get("preferred_agent_types", [])
                        if agent_def.agent_type in preferred_types:
                            agent_scores[agent_id] += 2.0
            
            # Sort by score and return top results
            sorted_agents = sorted(agent_scores.items(), key=lambda x: x[1], reverse=True)
            result_agent_ids = [agent_id for agent_id, score in sorted_agents[:limit]]
            
            # Get agent information with scores
            agents = []
            for agent_id in result_agent_ids:
                agent_info = await self._get_agent_info(agent_id)
                if agent_info:
                    agent_info["recommendation_score"] = agent_scores[agent_id]
                    agents.append(agent_info)
            
            return agents
    
    # Agent Metadata Management
    
    async def update_agent_metadata(self, agent_id: str, metadata: Dict[str, Any]) -> bool:
        """
        Update metadata for an agent.
        
        Args:
            agent_id: ID of the agent
            metadata: New metadata to merge with existing
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Update metadata
            self._agent_metadata[agent_id].update(metadata)
            
            # Update agent definition
            if agent_id in self._agents:
                self._agents[agent_id].metadata.update(metadata)
            
            # Update semantic index if description or keywords changed
            if "description" in metadata or "keywords" in metadata:
                # Rebuild semantic index for this agent
                for keyword, agent_ids in list(self._semantic_index.items()):
                    if agent_id in agent_ids:
                        agent_ids.remove(agent_id)
                        if not agent_ids:
                            del self._semantic_index[keyword]
                
                # Add new keywords
                keywords = metadata.get("keywords", [])
                for keyword in keywords:
                    self._semantic_index[keyword.lower()].append(agent_id)
            
            # Trigger update event
            await self._trigger_event(AgentLifecycleEvent.UPDATED, {
                "agent_id": agent_id,
                "metadata": metadata
            })
            
            # Persist changes
            await self._enhanced_save_agent_data()
            
            self.logger.info(f"Updated metadata for agent {agent_id}")
            return True
    
    async def get_agent_metadata(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent metadata if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return self._agent_metadata.get(agent_id)
    
    # Agent Health Monitoring and Status Tracking
    
    async def update_agent_health(self, agent_id: str, status: AgentHealthStatus, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update health status for an agent.
        
        Args:
            agent_id: ID of the agent
            status: New health status
            details: Optional details about the health status
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Update health status
            old_status = self._agent_health[agent_id]["status"]
            self._agent_health[agent_id] = {
                "status": status,
                "last_check": datetime.utcnow(),
                "details": details or {},
                "consecutive_failures": (
                    self._agent_health[agent_id]["consecutive_failures"] + 1
                    if status == AgentHealthStatus.UNHEALTHY
                    else 0
                )
            }
            
            # Update agent instance status
            if agent_id in self._agent_instances:
                if status == AgentHealthStatus.HEALTHY:
                    self._agent_instances[agent_id]["status"] = AgentStatus.READY
                elif status == AgentHealthStatus.DEGRADED:
                    self._agent_instances[agent_id]["status"] = AgentStatus.BUSY
                else:  # UNHEALTHY or UNKNOWN
                    self._agent_instances[agent_id]["status"] = AgentStatus.ERROR
            
            # Record metrics
            if self._metrics_service:
                if status == AgentHealthStatus.HEALTHY:
                    await self._metrics_service.record_agent_success(agent_id)
                else:
                    await self._metrics_service.record_agent_failure(agent_id)
            
            # Check for status change
            if old_status != status:
                # Trigger health check event
                await self._trigger_event(AgentLifecycleEvent.HEALTH_CHECK, {
                    "agent_id": agent_id,
                    "old_status": old_status.value,
                    "new_status": status.value,
                    "details": details or {}
                })
                
                # Check for alerts
                await self._check_health_alerts(agent_id, status, details or {})
            
            self.logger.info(f"Updated health status for agent {agent_id} to {status}")
            
            # Notify monitor about health status change
            await self.notify_monitor_agent_health_change(agent_id, status, details)
            
            return True
    
    async def get_agent_health(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get health status for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent health information if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_health:
                return None
            
            health_data = self._agent_health[agent_id].copy()
            
            # Add uptime information
            if agent_id in self._agent_performance:
                perf = self._agent_performance[agent_id]
                if perf["uptime_start"]:
                    uptime = datetime.utcnow() - perf["uptime_start"]
                    health_data["uptime_seconds"] = uptime.total_seconds()
                
                # Add recent performance metrics
                if perf["response_times"]:
                    health_data["avg_response_time"] = sum(perf["response_times"]) / len(perf["response_times"])
                
                if perf["success_rates"]:
                    health_data["avg_success_rate"] = sum(perf["success_rates"]) / len(perf["success_rates"])
                
                # Add error counts
                health_data["error_counts"] = dict(perf["error_counts"])
            
            return health_data
    
    async def check_agent_health(self, agent_id: str) -> bool:
        """
        Perform health check for a specific agent.
        
        Args:
            agent_id: ID of the agent to check
            
        Returns:
            True if agent is healthy, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                return False
            
            # Check if agent has been seen recently
            if agent_id in self._agent_instances:
                last_seen = self._agent_instances[agent_id]["last_seen"]
                if (datetime.utcnow() - last_seen).total_seconds() > self._agent_timeout_seconds:
                    # Agent timeout
                    await self.update_agent_health(agent_id, AgentHealthStatus.UNHEALTHY, {
                        "reason": "timeout",
                        "last_seen": last_seen.isoformat()
                    })
                    return False
            
            # Check health status
            health = self._agent_health.get(agent_id, {})
            return health.get("status") == AgentHealthStatus.HEALTHY
    
    # Agent Versioning and Compatibility Checking
    
    async def update_agent_version(self, agent_id: str, version: str, compatible_versions: Optional[List[str]] = None) -> bool:
        """
        Update version information for an agent.
        
        Args:
            agent_id: ID of the agent
            version: New version
            compatible_versions: List of compatible versions
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Update version
            old_version = self._agent_versions[agent_id]["current"]
            self._agent_versions[agent_id]["current"] = version
            
            # Update compatible versions
            if compatible_versions:
                self._agent_versions[agent_id]["compatible"] = compatible_versions
            
            # Update agent definition
            if agent_id in self._agents:
                self._agents[agent_id].version = version
            
            # Trigger update event
            await self._trigger_event(AgentLifecycleEvent.UPDATED, {
                "agent_id": agent_id,
                "old_version": old_version,
                "new_version": version,
                "compatible_versions": compatible_versions
            })
            
            self.logger.info(f"Updated version for agent {agent_id} to {version}")
            return True
    
    async def check_agent_compatibility(self, agent_id: str, required_version: str) -> bool:
        """
        Check if an agent version is compatible with a required version.
        
        Args:
            agent_id: ID of the agent
            required_version: Required version
            
        Returns:
            True if compatible, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_versions:
                return False
            
            current_version = self._agent_versions[agent_id]["current"]
            compatible_versions = self._agent_versions[agent_id]["compatible"]
            
            # Check if current version matches required
            if current_version == required_version:
                return True
            
            # Check if required version is in compatible list
            if required_version in compatible_versions:
                return True
            
            # Simple semantic versioning check
            try:
                # Split version strings
                current_parts = [int(part) for part in current_version.split('.')]
                required_parts = [int(part) for part in required_version.split('.')]
                
                # Compare major version
                if current_parts[0] != required_parts[0]:
                    return False
                
                # For now, consider same major version as compatible
                # In a real implementation, this would be more sophisticated
                return True
            except (ValueError, IndexError):
                # Fallback to exact match if version parsing fails
                return False
    
    async def get_agent_version(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get version information for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Version information if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return self._agent_versions.get(agent_id)
    
    # Agent Dependency Management
    
    async def add_agent_dependency(self, agent_id: str, dependency_id: str) -> bool:
        """
        Add a dependency for an agent.
        
        Args:
            agent_id: ID of the agent
            dependency_id: ID of the dependency
            
        Returns:
            True if addition was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            # Check if both agents exist
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            if dependency_id not in self._agents:
                self.logger.warning(f"Dependency agent {dependency_id} not found in registry")
                return False
            
            # Add dependency
            self._agent_dependencies[agent_id].add(dependency_id)
            
            # Update relationships
            if "depends_on" not in self._agent_relationships[agent_id]:
                self._agent_relationships[agent_id]["depends_on"] = []
            
            if dependency_id not in self._agent_relationships[agent_id]["depends_on"]:
                self._agent_relationships[agent_id]["depends_on"].append(dependency_id)
            
            if "used_by" not in self._agent_relationships[dependency_id]:
                self._agent_relationships[dependency_id]["used_by"] = []
            
            if agent_id not in self._agent_relationships[dependency_id]["used_by"]:
                self._agent_relationships[dependency_id]["used_by"].append(agent_id)
            
            self.logger.info(f"Added dependency {dependency_id} for agent {agent_id}")
            return True
    
    async def remove_agent_dependency(self, agent_id: str, dependency_id: str) -> bool:
        """
        Remove a dependency for an agent.
        
        Args:
            agent_id: ID of the agent
            dependency_id: ID of the dependency
            
        Returns:
            True if removal was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            # Check if dependency exists
            if agent_id not in self._agent_dependencies or dependency_id not in self._agent_dependencies[agent_id]:
                self.logger.warning(f"Dependency {dependency_id} not found for agent {agent_id}")
                return False
            
            # Remove dependency
            self._agent_dependencies[agent_id].remove(dependency_id)
            
            # Update relationships
            if "depends_on" in self._agent_relationships[agent_id]:
                if dependency_id in self._agent_relationships[agent_id]["depends_on"]:
                    self._agent_relationships[agent_id]["depends_on"].remove(dependency_id)
            
            if "used_by" in self._agent_relationships[dependency_id]:
                if agent_id in self._agent_relationships[dependency_id]["used_by"]:
                    self._agent_relationships[dependency_id]["used_by"].remove(agent_id)
            
            self.logger.info(f"Removed dependency {dependency_id} for agent {agent_id}")
            return True
    
    async def get_agent_dependencies(self, agent_id: str) -> List[str]:
        """
        Get dependencies for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            List of dependency IDs
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return list(self._agent_dependencies.get(agent_id, set()))
    
    async def get_agent_dependents(self, agent_id: str) -> List[str]:
        """
        Get agents that depend on the specified agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            List of dependent agent IDs
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            dependents = []
            for dep_agent_id, dependencies in self._agent_dependencies.items():
                if agent_id in dependencies:
                    dependents.append(dep_agent_id)
            
            return dependents
    
    # Dynamic Capability Updates and Versioning
    
    async def update_agent_capabilities(self, agent_id: str, capabilities: List[Union[str, AgentCapability]],
                                     version: Optional[str] = None) -> bool:
        """
        Update an agent's capabilities dynamically.
        
        Args:
            agent_id: ID of the agent
            capabilities: New list of capabilities
            version: Optional version for the capabilities
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Convert string capabilities to AgentCapability objects if needed
            agent_capabilities = []
            for cap in capabilities:
                if isinstance(cap, str):
                    agent_capabilities.append(AgentCapability(name=cap))
                else:
                    agent_capabilities.append(cap)
            
            # Get old capabilities for comparison
            old_capabilities = self._agents[agent_id].capabilities.copy()
            old_capability_names = {cap.name for cap in old_capabilities}
            new_capability_names = {cap.name for cap in agent_capabilities}
            
            # Update agent capabilities
            self._agents[agent_id].capabilities = agent_capabilities
            
            # Update capability version if provided
            if version:
                await self.update_agent_version(agent_id, version)
            
            # Update capability index
            # Remove agent from old capabilities that are no longer present
            for cap_name in old_capability_names - new_capability_names:
                if agent_id in self._capability_index.get(cap_name, set()):
                    self._capability_index[cap_name].remove(agent_id)
                    if not self._capability_index[cap_name]:
                        del self._capability_index[cap_name]
            
            # Add agent to new capabilities
            for cap in agent_capabilities:
                if cap.name not in old_capability_names:
                    self._capability_index[cap.name].add(agent_id)
            
            # Trigger capability update event
            await self._trigger_event(AgentLifecycleEvent.UPDATED, {
                "agent_id": agent_id,
                "old_capabilities": [cap.name for cap in old_capabilities],
                "new_capabilities": [cap.name for cap in agent_capabilities],
                "version": version
            })
            
            self.logger.info(f"Updated capabilities for agent {agent_id}")
            return True
    
    async def add_agent_capability(self, agent_id: str, capability: Union[str, AgentCapability],
                                 version: Optional[str] = None) -> bool:
        """
        Add a new capability to an agent.
        
        Args:
            agent_id: ID of the agent
            capability: Capability to add
            version: Optional version for the capability
            
        Returns:
            True if addition was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Convert string capability to AgentCapability object if needed
            if isinstance(capability, str):
                cap_obj = AgentCapability(name=capability)
            else:
                cap_obj = capability
            
            # Check if agent already has this capability
            existing_capabilities = [cap.name for cap in self._agents[agent_id].capabilities]
            if cap_obj.name in existing_capabilities:
                self.logger.warning(f"Agent {agent_id} already has capability {cap_obj.name}")
                return False
            
            # Add capability to agent
            self._agents[agent_id].capabilities.append(cap_obj)
            
            # Update capability index
            self._capability_index[cap_obj.name].add(agent_id)
            
            # Create embedding for the capability if it doesn't exist
            if cap_obj.name not in self._capability_embeddings:
                await self.create_capability_embedding(cap_obj.name)
            
            # Update agent version if provided
            if version:
                await self.update_agent_version(agent_id, version)
            
            # Trigger capability update event
            await self._trigger_event(AgentLifecycleEvent.UPDATED, {
                "agent_id": agent_id,
                "added_capability": cap_obj.name,
                "version": version
            })
            
            self.logger.info(f"Added capability {cap_obj.name} to agent {agent_id}")
            return True
    
    async def remove_agent_capability(self, agent_id: str, capability: str,
                                    version: Optional[str] = None) -> bool:
        """
        Remove a capability from an agent.
        
        Args:
            agent_id: ID of the agent
            capability: Name of the capability to remove
            version: Optional version for the capability
            
        Returns:
            True if removal was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Find and remove the capability
            agent = self._agents[agent_id]
            capability_found = False
            
            for i, cap in enumerate(agent.capabilities):
                if cap.name == capability:
                    del agent.capabilities[i]
                    capability_found = True
                    break
            
            if not capability_found:
                self.logger.warning(f"Agent {agent_id} does not have capability {capability}")
                return False
            
            # Update capability index
            if agent_id in self._capability_index.get(capability, set()):
                self._capability_index[capability].remove(agent_id)
                if not self._capability_index[capability]:
                    del self._capability_index[capability]
            
            # Update agent version if provided
            if version:
                await self.update_agent_version(agent_id, version)
            
            # Trigger capability update event
            await self._trigger_event(AgentLifecycleEvent.UPDATED, {
                "agent_id": agent_id,
                "removed_capability": capability,
                "version": version
            })
            
            self.logger.info(f"Removed capability {capability} from agent {agent_id}")
            return True
    
    async def get_capability_version(self, agent_id: str, capability: str) -> Optional[str]:
        """
        Get the version of a specific capability for an agent.
        
        Args:
            agent_id: ID of the agent
            capability: Name of the capability
            
        Returns:
            Version of the capability if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                return None
            
            # Find the capability in the agent's capabilities
            for cap in self._agents[agent_id].capabilities:
                if cap.name == capability:
                    return cap.version
            
            return None
    
    # Integration with Agent Orchestrator
    
    async def integrate_with_orchestrator(self, orchestrator_service) -> bool:
        """
        Integrate Agent Registry with Agent Orchestrator.
        
        Args:
            orchestrator_service: The Agent Orchestrator service instance
            
        Returns:
            True if integration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            self._orchestrator_service = orchestrator_service
            self._orchestrator_integration = True
            
            # Register event handlers for orchestrator events
            await self.add_event_handler(AgentLifecycleEvent.REGISTERED, self._handle_orchestrator_agent_registered)
            await self.add_event_handler(AgentLifecycleEvent.DEREGISTERED, self._handle_orchestrator_agent_deregistered)
            await self.add_event_handler(AgentLifecycleEvent.UPDATED, self._handle_orchestrator_agent_updated)
            
            # Register with orchestrator for agent discovery
            if hasattr(orchestrator_service, 'register_agent_registry'):
                await orchestrator_service.register_agent_registry(self)
            
            self.logger.info("Successfully integrated with Agent Orchestrator")
            return True
        except Exception as e:
            self.logger.error(f"Failed to integrate with Agent Orchestrator: {e}")
            return False
    
    async def _handle_orchestrator_agent_registered(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle agent registration event for orchestrator integration.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            return
        
        try:
            agent_id = data.get("agent_id")
            if agent_id and hasattr(self._orchestrator_service, 'on_agent_registered'):
                # Notify orchestrator about agent registration
                agent_info = await self._get_agent_info(agent_id)
                await self._orchestrator_service.on_agent_registered(agent_info)
        except Exception as e:
            self.logger.error(f"Error handling orchestrator agent registration: {e}")
    
    async def _handle_orchestrator_agent_deregistered(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle agent deregistration event for orchestrator integration.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            return
        
        try:
            agent_id = data.get("agent_id")
            if agent_id and hasattr(self._orchestrator_service, 'on_agent_deregistered'):
                # Notify orchestrator about agent deregistration
                await self._orchestrator_service.on_agent_deregistered(agent_id)
        except Exception as e:
            self.logger.error(f"Error handling orchestrator agent deregistration: {e}")
    
    async def _handle_orchestrator_agent_updated(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle agent update event for orchestrator integration.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            return
        
        try:
            agent_id = data.get("agent_id")
            if agent_id and hasattr(self._orchestrator_service, 'on_agent_updated'):
                # Notify orchestrator about agent update
                agent_info = await self._get_agent_info(agent_id)
                await self._orchestrator_service.on_agent_updated(agent_info)
        except Exception as e:
            self.logger.error(f"Error handling orchestrator agent update: {e}")
    
    async def request_agent_from_orchestrator(self, task_type: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Request an agent from orchestrator for a specific task.
        
        Args:
            task_type: Type of task to find an agent for
            context: Optional context for task
            
        Returns:
            Agent information if found, None otherwise
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            self.logger.warning("Orchestrator integration not available")
            return None
        
        try:
            if hasattr(self._orchestrator_service, 'request_agent'):
                # Request agent from orchestrator
                agent = await self._orchestrator_service.request_agent(task_type, context)
                return agent
            else:
                # Fallback to local agent recommendation
                agents = await self.recommend_agents(task_type, context, limit=1)
                return agents[0] if agents else None
        except Exception as e:
            self.logger.error(f"Error requesting agent from orchestrator: {e}")
            return None
    
    async def notify_orchestrator_agent_health_change(self, agent_id: str, health_status: AgentHealthStatus) -> None:
        """
        Notify orchestrator about an agent's health status change.
        
        Args:
            agent_id: ID of the agent
            health_status: New health status
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            return
        
        try:
            if hasattr(self._orchestrator_service, 'on_agent_health_change'):
                await self._orchestrator_service.on_agent_health_change(agent_id, health_status)
        except Exception as e:
            self.logger.error(f"Error notifying orchestrator about agent health change: {e}")
    
    async def get_orchestrator_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get agent status from the orchestrator.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent status information if found, None otherwise
        """
        if not self._orchestrator_integration or not hasattr(self, '_orchestrator_service'):
            return None
        
        try:
            if hasattr(self._orchestrator_service, 'get_agent_status'):
                return await self._orchestrator_service.get_agent_status(agent_id)
            else:
                # Fallback to local agent status
                agent_info = await self._get_agent_info(agent_id)
                if agent_info:
                    return {
                        "agent_id": agent_id,
                        "status": agent_info.get("status"),
                        "health": agent_info.get("health", {})
                    }
                return None
        except Exception as e:
            self.logger.error(f"Error getting agent status from orchestrator: {e}")
            return None
    
    # Integration with Agent Monitor
    
    async def integrate_with_monitor(self, monitor_service) -> bool:
        """
        Integrate Agent Registry with Agent Monitor for health status updates.
        
        Args:
            monitor_service: The Agent Monitor service instance
            
        Returns:
            True if integration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            self._monitor_service = monitor_service
            self._monitor_integration = True
            
            # Register event handlers for monitor events
            await self.add_event_handler(AgentLifecycleEvent.HEALTH_CHECK, self._handle_monitor_health_update)
            await self.add_event_handler(AgentLifecycleEvent.HEARTBEAT, self._handle_monitor_heartbeat)
            
            # Register with monitor for health status updates
            if hasattr(monitor_service, 'register_agent_registry'):
                await monitor_service.register_agent_registry(self)
            
            self.logger.info("Successfully integrated with Agent Monitor")
            return True
        except Exception as e:
            self.logger.error(f"Failed to integrate with Agent Monitor: {e}")
            return False
    
    async def _handle_monitor_health_update(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle health update event from monitor integration.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._monitor_integration or not hasattr(self, '_monitor_service'):
            return
        
        try:
            agent_id = data.get("agent_id")
            if agent_id and hasattr(self._monitor_service, 'on_agent_health_update'):
                # Notify monitor about agent health update
                health_data = await self.get_agent_health(agent_id)
                await self._monitor_service.on_agent_health_update(agent_id, health_data)
        except Exception as e:
            self.logger.error(f"Error handling monitor health update: {e}")
    
    async def _handle_monitor_heartbeat(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle heartbeat event from monitor integration.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._monitor_integration or not hasattr(self, '_monitor_service'):
            return
        
        try:
            agent_id = data.get("agent_id")
            if agent_id and hasattr(self._monitor_service, 'on_agent_heartbeat'):
                # Notify monitor about agent heartbeat
                heartbeat = self._agent_heartbeats.get(agent_id)
                if heartbeat:
                    await self._monitor_service.on_agent_heartbeat(agent_id, heartbeat)
        except Exception as e:
            self.logger.error(f"Error handling monitor heartbeat: {e}")
    
    async def notify_monitor_agent_health_change(self, agent_id: str, health_status: AgentHealthStatus, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Notify monitor about an agent's health status change.
        
        Args:
            agent_id: ID of the agent
            health_status: New health status
            details: Optional details about the health status change
        """
        if not self._monitor_integration or not hasattr(self, '_monitor_service'):
            return
        
        try:
            if hasattr(self._monitor_service, 'on_agent_health_change'):
                await self._monitor_service.on_agent_health_change(agent_id, health_status, details)
        except Exception as e:
            self.logger.error(f"Error notifying monitor about agent health change: {e}")
    
    async def get_monitor_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get agent status from the monitor.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent status information if found, None otherwise
        """
        if not self._monitor_integration or not hasattr(self, '_monitor_service'):
            return None
        
        try:
            if hasattr(self._monitor_service, 'get_agent_status'):
                return await self._monitor_service.get_agent_status(agent_id)
            else:
                # Fallback to local agent status
                agent_info = await self._get_agent_info(agent_id)
                if agent_info:
                    return {
                        "agent_id": agent_id,
                        "status": agent_info.get("status"),
                        "health": agent_info.get("health", {})
                    }
                return None
        except Exception as e:
            self.logger.error(f"Error getting agent status from monitor: {e}")
            return None
    
    # Enhanced Unified Memory Service Integration
    
    async def connect_to_memory_service(self, memory_service) -> bool:
        """
        Connect to Unified Memory Service for persistent agent metadata storage.
        
        Args:
            memory_service: The Unified Memory Service instance
            
        Returns:
            True if connection was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            self._memory_service = memory_service
            global HAS_MEMORY_SERVICE
            HAS_MEMORY_SERVICE = True
            
            # Initialize memory collections if they don't exist
            await self._initialize_memory_collections()
            
            # Load existing agent data
            await self._enhanced_load_agent_data()
            
            self.logger.info("Successfully connected to Unified Memory Service")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to Unified Memory Service: {e}")
            return False
    
    async def _initialize_memory_collections(self) -> None:
        """Initialize memory collections for agent registry data."""
        if not self._memory_service or not HAS_MEMORY_SERVICE:
            return
        
        try:
            # Create collections for agent registry data
            collections = [
                "agent_registry_agents",
                "agent_registry_metadata",
                "agent_registry_health",
                "agent_registry_versions",
                "agent_registry_dependencies",
                "agent_registry_capabilities",
                "agent_registry_performance",
                "agent_registry_topology",
                "agent_registry_embeddings",
                "agent_registry_hierarchy"
            ]
            
            for collection in collections:
                if hasattr(self._memory_service, 'create_collection'):
                    await self._memory_service.create_collection(collection)
            
            self.logger.info("Initialized memory collections for agent registry")
        except Exception as e:
            self.logger.error(f"Failed to initialize memory collections: {e}")
    
    async def _enhanced_save_agent_data(self) -> None:
        """Enhanced method to save agent data to the memory service."""
        if not self._memory_service or not HAS_MEMORY_SERVICE:
            return
        
        try:
            # Save agent definitions with enhanced metadata
            agents_data = []
            for agent_id, agent_def in self._agents.items():
                agent_data = agent_def.dict()
                
                # Add registry-specific metadata
                agent_data["registry_metadata"] = {
                    "last_heartbeat": self._agent_heartbeats.get(agent_id).timestamp.isoformat() if agent_id in self._agent_heartbeats else None,
                    "network_topology": self._network_topology.get(agent_id).__dict__ if agent_id in self._network_topology else None,
                    "performance_summary": await self.get_agent_performance(agent_id) if agent_id in self._agent_performance else None
                }
                
                agents_data.append(agent_data)
            
            await self._memory_service.store("agent_registry_agents", "definitions", agents_data)
            
            # Save capability embeddings
            embeddings_data = []
            for cap_name, embedding in self._capability_embeddings.items():
                embeddings_data.append({
                    "capability": cap_name,
                    "embedding": embedding.embedding.tolist(),
                    "version": embedding.version,
                    "last_updated": embedding.last_updated.isoformat()
                })
            
            await self._memory_service.store("agent_registry_embeddings", "embeddings", embeddings_data)
            
            # Save network topology
            topology_data = []
            for agent_id, topology in self._network_topology.items():
                topology_data.append({
                    "agent_id": agent_id,
                    "neighbors": list(topology.neighbors),
                    "network_distance": topology.network_distance,
                    "network_position": topology.network_position,
                    "connection_quality": topology.connection_quality
                })
            
            await self._memory_service.store("agent_registry_topology", "topology", topology_data)
            
            # Save performance analytics
            performance_data = []
            for agent_id, perf in self._agent_performance.items():
                performance_data.append({
                    "agent_id": agent_id,
                    "response_times": list(perf["response_times"]) if perf["response_times"] else [],
                    "success_rates": list(perf["success_rates"]) if perf["success_rates"] else [],
                    "error_counts": dict(perf["error_counts"]),
                    "last_activity": perf["last_activity"].isoformat() if perf["last_activity"] else None,
                    "uptime_start": perf["uptime_start"].isoformat() if perf["uptime_start"] else None
                })
            
            await self._memory_service.store("agent_registry_performance", "analytics", performance_data)
            
            self.logger.info(f"Enhanced save of agent data to memory service completed")
        except Exception as e:
            self.logger.error(f"Failed to enhanced save agent data to memory service: {e}")
    
    async def _enhanced_load_agent_data(self) -> None:
        """Enhanced method to load agent data from the memory service."""
        if not self._memory_service or not HAS_MEMORY_SERVICE:
            return
        
        try:
            # Load agent definitions with enhanced metadata
            agents_data = await self._memory_service.retrieve("agent_registry_agents", "definitions")
            if agents_data:
                for agent_data in agents_data:
                    try:
                        agent_def = AgentDefinition(**agent_data)
                        self._agents[agent_def.agent_id] = agent_def
                        
                        # Load registry-specific metadata
                        if "registry_metadata" in agent_data:
                            registry_meta = agent_data["registry_metadata"]
                            
                            # Load heartbeat data
                            if registry_meta.get("last_heartbeat"):
                                heartbeat_time = datetime.fromisoformat(registry_meta["last_heartbeat"])
                                if agent_def.agent_id not in self._agent_heartbeats:
                                    self._agent_heartbeats[agent_def.agent_id] = AgentHeartbeat(
                                        agent_id=agent_def.agent_id,
                                        timestamp=heartbeat_time,
                                        status=AgentHealthStatus.HEALTHY,
                                        endpoint=agent_def.endpoint or "",
                                        capabilities=[cap.name for cap in agent_def.capabilities]
                                    )
                            
                            # Load network topology
                            if registry_meta.get("network_topology"):
                                topology_data = registry_meta["network_topology"]
                                if agent_def.agent_id not in self._network_topology:
                                    self._network_topology[agent_def.agent_id] = AgentNetworkTopology(
                                        agent_id=agent_def.agent_id,
                                        neighbors=set(topology_data.get("neighbors", [])),
                                        network_distance=topology_data.get("network_distance", {}),
                                        network_position=tuple(topology_data.get("network_position", (0.0, 0.0))),
                                        connection_quality=topology_data.get("connection_quality", {})
                                    )
                    except Exception as e:
                        self.logger.error(f"Error loading agent data for {agent_data.get('agent_id', 'unknown')}: {e}")
            
            # Load capability embeddings
            embeddings_data = await self._memory_service.retrieve("agent_registry_embeddings", "embeddings")
            if embeddings_data:
                for embedding_data in embeddings_data:
                    try:
                        cap_name = embedding_data["capability"]
                        embedding_array = np.array(embedding_data["embedding"])
                        
                        self._capability_embeddings[cap_name] = CapabilityEmbedding(
                            capability=cap_name,
                            embedding=embedding_array,
                            version=embedding_data.get("version", "1.0"),
                            last_updated=datetime.fromisoformat(embedding_data["last_updated"]) if embedding_data.get("last_updated") else datetime.utcnow()
                        )
                    except Exception as e:
                        self.logger.error(f"Error loading embedding for {embedding_data.get('capability', 'unknown')}: {e}")
            
            # Load network topology
            topology_data = await self._memory_service.retrieve("agent_registry_topology", "topology")
            if topology_data:
                for topo_data in topology_data:
                    try:
                        agent_id = topo_data["agent_id"]
                        if agent_id not in self._network_topology:
                            self._network_topology[agent_id] = AgentNetworkTopology(
                                agent_id=agent_id,
                                neighbors=set(topo_data.get("neighbors", [])),
                                network_distance=topo_data.get("network_distance", {}),
                                network_position=tuple(topo_data.get("network_position", (0.0, 0.0)))
                            )
                    except Exception as e:
                        self.logger.error(f"Error loading topology for {topo_data.get('agent_id', 'unknown')}: {e}")
            
            # Load performance analytics
            performance_data = await self._memory_service.retrieve("agent_registry_performance", "analytics")
            if performance_data:
                for perf_data in performance_data:
                    try:
                        agent_id = perf_data["agent_id"]
                        if agent_id not in self._agent_performance:
                            self._agent_performance[agent_id] = {
                                "response_times": deque(perf_data.get("response_times", []), maxlen=100),
                                "success_rates": deque(perf_data.get("success_rates", []), maxlen=100),
                                "error_counts": defaultdict(int, perf_data.get("error_counts", {})),
                                "last_activity": datetime.fromisoformat(perf_data["last_activity"]) if perf_data.get("last_activity") else datetime.utcnow(),
                                "uptime_start": datetime.fromisoformat(perf_data["uptime_start"]) if perf_data.get("uptime_start") else datetime.utcnow(),
                                "downtime_periods": []
                            }
                    except Exception as e:
                        self.logger.error(f"Error loading performance data for {perf_data.get('agent_id', 'unknown')}: {e}")
            
            self.logger.info(f"Enhanced load of agent data from memory service completed")
        except Exception as e:
            self.logger.error(f"Failed to enhanced load agent data from memory service: {e}")
    
    async def backup_agent_registry(self, backup_id: Optional[str] = None) -> str:
        """
        Create a backup of agent registry data.
        
        Args:
            backup_id: Optional identifier for the backup
            
        Returns:
            Backup identifier
        """
        if not self._memory_service or not HAS_MEMORY_SERVICE:
            raise RuntimeError("Memory service not available for backup")
        
        try:
            if not backup_id:
                backup_id = f"agent_registry_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            
            # Create a comprehensive backup
            backup_data = {
                "agents": [agent.dict() for agent in self._agents.values()],
                "metadata": dict(self._agent_metadata),
                "health": dict(self._agent_health),
                "versions": dict(self._agent_versions),
                "dependencies": {k: list(v) for k, v in self._agent_dependencies.items()},
                "capabilities": {k: list(v) for k, v in self._capability_index.items()},
                "performance": {k: {
                    "response_times": list(v["response_times"]),
                    "success_rates": list(v["success_rates"]),
                    "error_counts": dict(v["error_counts"]),
                    "last_activity": v["last_activity"].isoformat() if v["last_activity"] else None,
                    "uptime_start": v["uptime_start"].isoformat() if v["uptime_start"] else None
                } for k, v in self._agent_performance.items()},
                "topology": {k: {
                    "neighbors": list(v.neighbors),
                    "network_distance": v.network_distance,
                    "network_position": v.network_position,
                    "connection_quality": v.connection_quality
                } for k, v in self._network_topology.items()},
                "embeddings": {k: {
                    "capability": v.capability,
                    "embedding": v.embedding.tolist(),
                    "version": v.version,
                    "last_updated": v.last_updated.isoformat()
                } for k, v in self._capability_embeddings.items()},
                "hierarchy": {
                    "parent_child": self._capability_hierarchy._parent_child_map,
                    "child_parent": self._capability_hierarchy._child_parent_map,
                    "attributes": self._capability_hierarchy._capability_attributes
                },
                "timestamp": datetime.utcnow().isoformat(),
                "backup_id": backup_id
            }
            
            # Store backup
            await self._memory_service.store("agent_registry_backups", backup_id, backup_data)
            
            self.logger.info(f"Created agent registry backup: {backup_id}")
            return backup_id
        except Exception as e:
            self.logger.error(f"Failed to create agent registry backup: {e}")
            raise
    
    async def restore_agent_registry(self, backup_id: str) -> bool:
        """
        Restore agent registry from a backup.
        
        Args:
            backup_id: Identifier of the backup to restore
            
        Returns:
            True if restore was successful, False otherwise
        """
        if not self._memory_service or not HAS_MEMORY_SERVICE:
            self.logger.error("Memory service not available for restore")
            return False
        
        try:
            # Load backup data
            backup_data = await self._memory_service.retrieve("agent_registry_backups", backup_id)
            if not backup_data:
                self.logger.error(f"Backup not found: {backup_id}")
                return False
        except Exception as e:
            self.logger.error(f"Error loading backup data: {e}")
            return False
        
        # Clear existing data
        async with self._lock:
            self._agents.clear()
            self._agent_metadata.clear()
            self._agent_health.clear()
            self._agent_versions.clear()
            self._agent_dependencies.clear()
            self._capability_index.clear()
            self._agent_performance.clear()
            self._network_topology.clear()
            self._capability_embeddings.clear()
            
            # Restore agents
            for agent_data in backup_data.get("agents", []):
                try:
                    agent_def = AgentDefinition(**agent_data)
                    self._agents[agent_def.agent_id] = agent_def
                except Exception as e:
                    self.logger.error(f"Error restoring agent {agent_data.get('agent_id', 'unknown')}: {e}")
            
            # Restore metadata
            self._agent_metadata.update(backup_data.get("metadata", {}))
            
            # Restore health
            self._agent_health.update(backup_data.get("health", {}))
            
            # Restore versions
            self._agent_versions.update(backup_data.get("versions", {}))
            
            # Restore dependencies
            for agent_id, dependencies in backup_data.get("dependencies", {}).items():
                self._agent_dependencies[agent_id] = set(dependencies)
            
            # Restore capabilities
            for capability, agent_ids in backup_data.get("capabilities", {}).items():
                self._capability_index[capability] = set(agent_ids)
            
            # Restore performance
            for agent_id, perf_data in backup_data.get("performance", {}).items():
                self._agent_performance[agent_id] = {
                    "response_times": deque(perf_data.get("response_times", []), maxlen=100),
                    "success_rates": deque(perf_data.get("success_rates", []), maxlen=100),
                    "error_counts": defaultdict(int, perf_data.get("error_counts", {})),
                    "last_activity": datetime.fromisoformat(perf_data["last_activity"]) if perf_data.get("last_activity") else datetime.utcnow(),
                    "uptime_start": datetime.fromisoformat(perf_data["uptime_start"]) if perf_data.get("uptime_start") else datetime.utcnow(),
                    "downtime_periods": []
                }
            
            # Restore topology
            for agent_id, topo_data in backup_data.get("topology", {}).items():
                self._network_topology[agent_id] = AgentNetworkTopology(
                    agent_id=agent_id,
                    neighbors=set(topo_data.get("neighbors", [])),
                    network_distance=topo_data.get("network_distance", {}),
                    network_position=tuple(topo_data.get("network_position", (0.0, 0.0))),
                    connection_quality=topo_data.get("connection_quality", {})
                )
            
            # Restore embeddings
            for cap_name, emb_data in backup_data.get("embeddings", {}).items():
                embedding_array = np.array(emb_data["embedding"])
                self._capability_embeddings[cap_name] = CapabilityEmbedding(
                    capability=cap_name,
                    embedding=embedding_array,
                    version=emb_data.get("version", "1.0"),
                    last_updated=datetime.fromisoformat(emb_data["last_updated"]) if emb_data.get("last_updated") else datetime.utcnow()
                )
            
            # Restore hierarchy
            hierarchy_data = backup_data.get("hierarchy", {})
            if "parent_child" in hierarchy_data:
                self._capability_hierarchy._parent_child_map = defaultdict(set, hierarchy_data["parent_child"])
            if "child_parent" in hierarchy_data:
                self._capability_hierarchy._child_parent_map = hierarchy_data["child_parent"]
            if "attributes" in hierarchy_data:
                self._capability_hierarchy._capability_attributes = defaultdict(dict, hierarchy_data["attributes"])
            
            self.logger.info(f"Restored agent registry from backup: {backup_id}")
            return True
    
    # Agent Lifecycle Event Handling
    
    async def add_event_handler(self, event_type: str, handler: Callable) -> None:
        """
        Add an event handler for a specific event type.
        
        Args:
            event_type: Type of event to handle
            handler: Handler function to call
        """
        self._event_handlers[event_type].append(handler)
    
    async def remove_event_handler(self, event_type: str, handler: Callable) -> None:
        """
        Remove an event handler for a specific event type.
        
        Args:
            event_type: Type of event
            handler: Handler function to remove
        """
        if handler in self._event_handlers[event_type]:
            self._event_handlers[event_type].remove(handler)
    
    async def _trigger_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Trigger an event and call all registered handlers.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        # Add to event history
        self._event_history.append({
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Call all handlers
        for handler in self._event_handlers[event_type]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                self.logger.error(f"Error in event handler for {event_type}: {e}")
    
    async def get_event_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get event history.
        
        Args:
            event_type: Optional event type to filter by
            limit: Maximum number of events to return
            
        Returns:
            List of event data
        """
        if not self._initialized:
            await self.initialize()
        
        events = list(self._event_history)
        
        # Filter by event type if specified
        if event_type:
            events = [event for event in events if event["event_type"] == event_type]
        
        # Sort by timestamp (newest first) and limit
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return events[:limit]
    
    # Agent Performance Tracking and Analytics
    
    async def record_agent_performance(self, agent_id: str, response_time: float, success: bool,
                                     error_type: Optional[str] = None, task_type: Optional[str] = None,
                                     resource_usage: Optional[Dict[str, float]] = None,
                                     metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Record performance metrics for an agent with enhanced tracking.
        
        Args:
            agent_id: ID of the agent
            response_time: Response time in seconds
            success: Whether the operation was successful
            error_type: Type of error if not successful
            task_type: Type of task performed
            resource_usage: Resource usage metrics during task execution
            metadata: Additional metadata about the task
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_performance:
                return
            
            # Initialize task-specific performance tracking if not exists
            if "task_performance" not in self._agent_performance[agent_id]:
                self._agent_performance[agent_id]["task_performance"] = {}
            
            # Record response time
            self._agent_performance[agent_id]["response_times"].append(response_time)
            self._agent_performance[agent_id]["last_activity"] = datetime.utcnow()
            
            # Record success/failure
            success_rate = 1.0 if success else 0.0
            self._agent_performance[agent_id]["success_rates"].append(success_rate)
            
            # Record error if not successful
            if not success and error_type:
                self._agent_performance[agent_id]["error_counts"][error_type] += 1
            
            # Record task-specific performance if task_type is provided
            if task_type:
                if task_type not in self._agent_performance[agent_id]["task_performance"]:
                    self._agent_performance[agent_id]["task_performance"][task_type] = {
                        "response_times": deque(maxlen=50),
                        "success_rates": deque(maxlen=50),
                        "error_counts": defaultdict(int),
                        "last_executed": datetime.utcnow()
                    }
                
                task_perf = self._agent_performance[agent_id]["task_performance"][task_type]
                task_perf["response_times"].append(response_time)
                task_perf["success_rates"].append(success_rate)
                task_perf["last_executed"] = datetime.utcnow()
                
                if not success and error_type:
                    task_perf["error_counts"][error_type] += 1
            
            # Record resource usage if provided
            if resource_usage:
                if "resource_usage_patterns" not in self._agent_performance[agent_id]:
                    self._agent_performance[agent_id]["resource_usage_patterns"] = {
                        "cpu": deque(maxlen=100),
                        "memory": deque(maxlen=100),
                        "network": deque(maxlen=100),
                        "disk": deque(maxlen=100)
                    }
                
                patterns = self._agent_performance[agent_id]["resource_usage_patterns"]
                
                if "cpu" in resource_usage:
                    patterns["cpu"].append(resource_usage["cpu"])
                
                if "memory" in resource_usage:
                    patterns["memory"].append(resource_usage["memory"])
                
                if "network" in resource_usage:
                    patterns["network"].append(resource_usage["network"])
                
                if "disk" in resource_usage:
                    patterns["disk"].append(resource_usage["disk"])
                
                # Add to resource usage history for anomaly detection
                self._resource_usage_history[agent_id].append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "resources": resource_usage.copy(),
                    "task_type": task_type,
                    "response_time": response_time
                })
                
                # Keep only recent history
                if len(self._resource_usage_history[agent_id]) > 100:
                    self._resource_usage_history[agent_id] = self._resource_usage_history[agent_id][-100:]
            
            # Record to metrics service
            if self._metrics_service:
                if success:
                    await self._metrics_service.record_agent_success(agent_id)
                else:
                    await self._metrics_service.record_agent_failure(agent_id)
                
                await self._metrics_service.record_agent_execution_time(agent_id, response_time)
                
                # Record task-specific metrics if available
                # Note: These methods may not exist in the AgentMetrics class yet
                # if task_type and hasattr(self._metrics_service, 'record_agent_task_execution'):
                #     await self._metrics_service.record_agent_task_execution(
                #         agent_id, task_type, response_time, success
                #     )
                #
                # if resource_usage and hasattr(self._metrics_service, 'record_agent_resource_usage'):
                #     await self._metrics_service.record_agent_resource_usage(agent_id, resource_usage)
    
    async def get_agent_task_performance(self, agent_id: str, task_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get task-specific performance metrics for an agent.
        
        Args:
            agent_id: ID of the agent
            task_type: Optional task type to filter by
            
        Returns:
            Task-specific performance metrics if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_performance:
                return None
            
            perf = self._agent_performance[agent_id]
            
            # Check if task performance data exists
            if "task_performance" not in perf:
                return None
            
            # Get task-specific metrics
            if task_type:
                if task_type not in perf["task_performance"]:
                    return None
                
                task_perf = perf["task_performance"][task_type]
                
                # Calculate metrics
                metrics = {
                    "agent_id": agent_id,
                    "task_type": task_type,
                    "last_executed": task_perf["last_executed"].isoformat() if task_perf["last_executed"] else None
                }
                
                # Response time metrics
                if task_perf["response_times"]:
                    response_times = list(task_perf["response_times"])
                    metrics["response_time"] = {
                        "min": min(response_times),
                        "max": max(response_times),
                        "avg": sum(response_times) / len(response_times),
                        "count": len(response_times)
                    }
                
                # Success rate metrics
                if task_perf["success_rates"]:
                    success_rates = list(task_perf["success_rates"])
                    metrics["success_rate"] = {
                        "min": min(success_rates),
                        "max": max(success_rates),
                        "avg": sum(success_rates) / len(success_rates),
                        "count": len(success_rates)
                    }
                
                # Error counts
                metrics["error_counts"] = dict(task_perf["error_counts"])
                
                return metrics
            else:
                # Return all task performance metrics
                all_task_metrics = {}
                for task_type, task_perf in perf["task_performance"].items():
                    task_metrics = {
                        "last_executed": task_perf["last_executed"].isoformat() if task_perf["last_executed"] else None
                    }
                    
                    # Response time metrics
                    if task_perf["response_times"]:
                        response_times = list(task_perf["response_times"])
                        task_metrics["response_time"] = {
                            "min": min(response_times),
                            "max": max(response_times),
                            "avg": sum(response_times) / len(response_times),
                            "count": len(response_times)
                        }
                    
                    # Success rate metrics
                    if task_perf["success_rates"]:
                        success_rates = list(task_perf["success_rates"])
                        task_metrics["success_rate"] = {
                            "min": min(success_rates),
                            "max": max(success_rates),
                            "avg": sum(success_rates) / len(success_rates),
                            "count": len(success_rates)
                        }
                    
                    # Error counts
                    task_metrics["error_counts"] = dict(task_perf["error_counts"])
                    
                    all_task_metrics[task_type] = task_metrics
                
                return {
                    "agent_id": agent_id,
                    "task_performance": all_task_metrics
                }
    
    async def get_agent_resource_usage_patterns(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get resource usage patterns for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Resource usage patterns if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_performance:
                return None
            
            perf = self._agent_performance[agent_id]
            
            # Check if resource usage patterns exist
            if "resource_usage_patterns" not in perf:
                return None
            
            patterns = perf["resource_usage_patterns"]
            
            # Calculate metrics for each resource type
            metrics = {
                "agent_id": agent_id,
                "resource_patterns": {}
            }
            
            for resource_type, values in patterns.items():
                if values:
                    values_list = list(values)
                    metrics["resource_patterns"][resource_type] = {
                        "min": min(values_list),
                        "max": max(values_list),
                        "avg": sum(values_list) / len(values_list),
                        "current": values_list[-1] if values_list else None,
                        "trend": "increasing" if len(values_list) > 1 and values_list[-1] > values_list[-2] else "stable",
                        "count": len(values_list)
                    }
            
            return metrics
    
    async def get_agent_performance(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get performance metrics for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Performance metrics if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agent_performance:
                return None
            
            perf = self._agent_performance[agent_id]
            
            # Calculate metrics
            metrics = {
                "agent_id": agent_id,
                "last_activity": perf["last_activity"].isoformat() if perf["last_activity"] else None,
                "uptime_start": perf["uptime_start"].isoformat() if perf["uptime_start"] else None
            }
            
            # Response time metrics
            if perf["response_times"]:
                response_times = list(perf["response_times"])
                metrics["response_time"] = {
                    "min": min(response_times),
                    "max": max(response_times),
                    "avg": sum(response_times) / len(response_times),
                    "count": len(response_times)
                }
            
            # Success rate metrics
            if perf["success_rates"]:
                success_rates = list(perf["success_rates"])
                metrics["success_rate"] = {
                    "min": min(success_rates),
                    "max": max(success_rates),
                    "avg": sum(success_rates) / len(success_rates),
                    "count": len(success_rates)
                }
            
            # Error counts
            metrics["error_counts"] = dict(perf["error_counts"])
            
            # Downtime periods
            metrics["downtime_periods"] = list(perf["downtime_periods"])
            
            return metrics
    
    async def get_all_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for all agents.
        
        Returns:
            Dictionary of performance metrics by agent ID
        """
        if not self._initialized:
            await self.initialize()
        
        metrics = {}
        
        async with self._lock:
            for agent_id in self._agent_performance:
                metrics[agent_id] = await self.get_agent_performance(agent_id)
        
        return metrics
    
    # Helper Methods
    
    async def _get_agent_info(self, agent_id: str) -> Dict[str, Any]:
        """
        Get comprehensive information about an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent information dictionary
        """
        if agent_id not in self._agents:
            return {}
        
        agent_def = self._agents[agent_id]
        instance = self._agent_instances.get(agent_id, {})
        metadata = self._agent_metadata.get(agent_id, {})
        health = self._agent_health.get(agent_id, {})
        version = self._agent_versions.get(agent_id, {})
        
        return {
            "agent_id": agent_id,
            "name": agent_def.name,
            "description": agent_def.description,
            "agent_type": agent_def.agent_type,
            "version": version.get("current", "unknown"),
            "status": instance.get("status", agent_def.status),
            "capabilities": [cap.dict() for cap in agent_def.capabilities],
            "endpoint": agent_def.endpoint,
            "metadata": metadata,
            "health": health,
            "performance": await self.get_agent_performance(agent_id),
            "registered_at": agent_def.created_at.isoformat() if agent_def.created_at else None,
            "updated_at": agent_def.updated_at.isoformat() if agent_def.updated_at else None
        }
    
    async def _check_health_alerts(self, agent_id: str, status: AgentHealthStatus, details: Dict[str, Any]) -> None:
        """
        Check for health alerts and send notifications if needed.
        
        Args:
            agent_id: ID of the agent
            status: Current health status
            details: Health details
        """
        # Get performance metrics
        perf = self._agent_performance.get(agent_id, {})
        
        # Check response time
        if perf.get("response_times"):
            avg_response_time = sum(perf["response_times"]) / len(perf["response_times"])
            response_time_thresholds = self._alert_thresholds.get("response_time", {})
            
            if avg_response_time > response_time_thresholds.get("critical", 10.0):
                self._send_alert(agent_id, "critical", "high_response_time", {
                    "current": avg_response_time,
                    "threshold": response_time_thresholds.get("critical", 10.0)
                })
            elif avg_response_time > response_time_thresholds.get("warning", 5.0):
                self._send_alert(agent_id, "warning", "high_response_time", {
                    "current": avg_response_time,
                    "threshold": response_time_thresholds.get("warning", 5.0)
                })
        
        # Check error rate
        if perf.get("success_rates"):
            error_rate = 1.0 - (sum(perf["success_rates"]) / len(perf["success_rates"]))
            error_rate_thresholds = self._alert_thresholds.get("error_rate", {})
            
            if error_rate > error_rate_thresholds.get("critical", 0.2):
                self._send_alert(agent_id, "critical", "high_error_rate", {
                    "current": error_rate,
                    "threshold": error_rate_thresholds.get("critical", 0.2)
                })
            elif error_rate > error_rate_thresholds.get("warning", 0.1):
                self._send_alert(agent_id, "warning", "high_error_rate", {
                    "current": error_rate,
                    "threshold": error_rate_thresholds.get("warning", 0.1)
                })
        
        # Check health status
        if status == AgentHealthStatus.UNHEALTHY:
            self._send_alert(agent_id, "critical", "unhealthy", details)
        elif status == AgentHealthStatus.DEGRADED:
            self._send_alert(agent_id, "warning", "degraded", details)
    
    def _send_alert(self, agent_id: str, level: str, alert_type: str, details: Dict[str, Any]) -> None:
        """
        Send an alert notification.
        
        Args:
            agent_id: ID of the agent
            level: Alert level (warning, critical)
            alert_type: Type of alert
            details: Alert details
        """
        alert = {
            "agent_id": agent_id,
            "level": level,
            "type": alert_type,
            "details": details,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.logger.warning(f"Agent alert: {alert}")
        
        # Send to all notification handlers
        for handler in self._notification_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(alert))
                else:
                    handler(alert)
            except Exception as e:
                self.logger.error(f"Error in notification handler: {e}")
    
    # Background Tasks
    
    async def _health_monitor(self) -> None:
        """Background task to monitor agent health."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Check health of all agents
                async with self._lock:
                    agent_ids = list(self._agents.keys())
                
                for agent_id in agent_ids:
                    try:
                        # Check if agent has timed out
                        if not await self.check_agent_health(agent_id):
                            self.logger.warning(f"Agent {agent_id} health check failed")
                    except Exception as e:
                        self.logger.error(f"Error checking health for agent {agent_id}: {e}")
                
                # Sleep until next check
                await asyncio.sleep(self._health_check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(self._health_check_interval)
    
    async def _cleanup_old_data(self) -> None:
        """Background task to clean up old data."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Calculate cutoff time
                cutoff_time = datetime.utcnow() - timedelta(hours=self._metrics_retention_hours)
                
                async with self._lock:
                    # Clean up old performance metrics
                    for agent_id, perf in self._agent_performance.items():
                        # Keep only recent response times
                        if perf["response_times"]:
                            # This is handled by deque maxlen, but we could add additional logic
                            pass
                        
                        # Keep only recent success rates
                        if perf["success_rates"]:
                            # This is handled by deque maxlen, but we could add additional logic
                            pass
                        
                        # Clean old downtime periods
                        if perf["downtime_periods"]:
                            perf["downtime_periods"] = [
                                period for period in perf["downtime_periods"]
                                if datetime.fromisoformat(period["start"]) > cutoff_time
                            ]
                
                # Sleep for a while
                await asyncio.sleep(3600)  # Check every hour
                
            except Exception as e:
                self.logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(3600)
    
    async def _analytics_processor(self) -> None:
        """Background task to process analytics."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Process analytics data
                async with self._lock:
                    # This is where we would process analytics data
                    # For now, we'll just log that it's running
                    pass
                
                # Sleep for a while
                await asyncio.sleep(300)  # Process every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Error in analytics processor: {e}")
                await asyncio.sleep(300)
    
    # Legacy Methods (for backward compatibility)
    
    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific agent.
        
        Args:
            agent_id: Unique identifier of the agent
            
        Returns:
            Agent information if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            return await self._get_agent_info(agent_id)
    
    async def list_agents(self, agent_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all agents or agents of a specific type.
        
        Args:
            agent_type: Optional filter for agent type
            
        Returns:
            List of agent information
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            agents = []
            
            for agent_id, agent_def in self._agents.items():
                if agent_type and agent_def.agent_type != agent_type:
                    continue
                
                agents.append(await self._get_agent_info(agent_id))
            
            return agents
    
    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        """
        Update the status of an agent.
        
        Args:
            agent_id: Unique identifier of the agent
            status: New status (e.g., "active", "inactive", "error")
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent {agent_id} not found in registry")
                return False
            
            # Map string status to AgentStatus enum
            try:
                agent_status = AgentStatus(status)
            except ValueError:
                self.logger.error(f"Invalid agent status: {status}")
                return False
            
            # Update agent definition status
            self._agents[agent_id].status = agent_status
            
            # Update agent instance status
            if agent_id in self._agent_instances:
                self._agent_instances[agent_id]["status"] = agent_status
            
            # Persist changes
            await self._enhanced_save_agent_data()
            
            self.logger.info(f"Agent {agent_id} status updated to {status}")
            return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check of the service.
        
        Returns:
            Health status information
        """
        discovery_status = "inactive"
        if self._discovery_processor_task:
            if not self._discovery_processor_task.done():
                discovery_status = "active"
            else:
                discovery_status = "completed"
        
        return {
            "status": "healthy",
            "service": "agent_registry",
            "initialized": self._initialized,
            "registered_agents": len(self._agents),
            "discovery_status": discovery_status,
            "discovery_enabled": self._discovery_enabled,
            "discovered_agents_count": len(self._discovered_agents),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def start(self) -> bool:
        """
        Start the Agent Registry service.
        
        Returns:
            bool: True if service was started successfully, False otherwise
        """
        try:
            if self._started:
                self.logger.warning("Agent Registry already started")
                return True
            
            # Start background tasks
            self._health_monitor_task = asyncio.create_task(self._health_monitor())
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self._analytics_task = asyncio.create_task(self._update_analytics())
            
            # Start discovery processor task if discovery is enabled
            if self._discovery_enabled and not self._discovery_processor_task:
                self._discovery_processor_task = asyncio.create_task(self._discovery_processor())
                self.logger.info("Started discovery processor task")
            
            self._started = True
            self.logger.info("Agent Registry service started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start Agent Registry: {e}")
            return False
    
    async def stop(self) -> bool:
        """
        Stop the Agent Registry service.
        
        Returns:
            bool: True if service was stopped successfully, False otherwise
        """
        try:
            if not self._started:
                self.logger.warning("Agent Registry not started")
                return True
            
            # Cancel background tasks
            if self._health_monitor_task:
                self._health_monitor_task.cancel()
            if self._cleanup_task:
                self._cleanup_task.cancel()
            if self._analytics_task:
                self._analytics_task.cancel()
            
            # Cancel discovery processor task
            if self._discovery_processor_task:
                self._discovery_processor_task.cancel()
                self.logger.info("Cancelled discovery processor task")
            
            # Wait for tasks to complete
            if self._health_monitor_task and not self._health_monitor_task.done():
                await self._health_monitor_task
            if self._cleanup_task and not self._cleanup_task.done():
                await self._cleanup_task
            if self._analytics_task and not self._analytics_task.done():
                await self._analytics_task
            if self._discovery_processor_task and not self._discovery_processor_task.done():
                await self._discovery_processor_task
            
            self._started = False
            self.logger.info("Agent Registry service stopped successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to stop Agent Registry: {e}")
            return False
    
    async def _initialize_service(self) -> None:
        """Initialize agent registry service-specific resources."""
        # Initialize agent registry specific resources here
        # This is called by the BaseService.initialize() method
        pass
    
    async def _start_service(self) -> None:
        """Start agent registry service-specific resources."""
        # Start any background tasks or resources specific to agent registry
        # This is called by the BaseService.start() method
        pass
    
    async def _stop_service(self) -> None:
        """Stop agent registry service-specific resources."""
        # Stop any background tasks or resources specific to agent registry
        # This is called by the BaseService.stop() method
        # Cancel background tasks
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._analytics_task:
            self._analytics_task.cancel()
        
        # Cancel discovery processor task
        if self._discovery_processor_task:
            self._discovery_processor_task.cancel()
            self.logger.info("Cancelled discovery processor task in _stop_service")
    
    async def _health_check_service(self) -> Dict[str, Any]:
        """Check health of agent registry service-specific resources."""
        # Check health of service-specific resources
        # This is called by the BaseService.health_check() method
        return {
            "healthy": self._initialized,
            "message": "Agent registry service is running" if self._initialized else "Agent registry service is not initialized",
            "background_tasks": {
                "health_monitor": self._health_monitor_task is not None and not self._health_monitor_task.done(),
                "cleanup": self._cleanup_task is not None and not self._cleanup_task.done(),
                "analytics": self._analytics_task is not None and not self._analytics_task.done(),
                "discovery_processor": self._discovery_processor_task is not None and not self._discovery_processor_task.done()
            },
            "discovery": {
                "enabled": self._discovery_enabled,
                "active": self._discovery_processor_task is not None and not self._discovery_processor_task.done(),
                "discovered_agents": len(self._discovered_agents),
                "discovery_sources": len(self._discovery_sources)
            }
        }
    
    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup task for agent registry."""
        while True:
            try:
                # Clean up expired sessions
                now = datetime.utcnow()
                expired_agents = []
                
                async with self._lock:
                    for agent_id, agent_info in self._agents.items():
                        # Check if agent has been inactive for too long
                        if agent_info.last_active and (now - agent_info.last_active).days > 30:
                            expired_agents.append(agent_id)
                
                # Unregister expired agents
                for agent_id in expired_agents:
                    logger.info(f"Unregistering expired agent {agent_id}")
                    await self.unregister_agent(agent_id)
                
                # Sleep for a day
                await asyncio.sleep(86400)  # 24 hours
                
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
                await asyncio.sleep(3600)  # 1 hour before retry
    
    async def _update_analytics(self) -> None:
        """Update analytics for agent registry."""
        while True:
            try:
                # Collect analytics data
                async with self._lock:
                    analytics = {
                        "total_agents": len(self._agents),
                        "active_agents": sum(1 for agent in self._agents.values() if agent.status == AgentStatus.READY),
                        "busy_agents": sum(1 for agent in self._agents.values() if agent.status == AgentStatus.BUSY),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                
                # Log analytics
                logger.info(f"Agent registry analytics: {analytics}")
                
                # Sleep for an hour
                await asyncio.sleep(3600)  # 1 hour
                
            except Exception as e:
                logger.error(f"Error updating analytics: {e}")
                await asyncio.sleep(600)  # 10 minutes before retry
    
    # Authentication and Authorization Methods
    
    async def authenticate_agent(self, agent_id: str, credentials: Dict[str, Any]) -> Optional[str]:
        """
        Authenticate an agent using Karen's auth systems.
        
        Args:
            agent_id: ID of the agent to authenticate
            credentials: Authentication credentials (token, certificate, etc.)
            
        Returns:
            Authentication token if successful, None otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._auth_manager:
            self.logger.error("Authentication manager not available")
            return None
        
        try:
            # For now, implement a simple authentication mechanism
            # In a real implementation, this would use the AuthenticationManager properly
            agent_api_key = credentials.get("api_key")
            if agent_api_key:
                # Validate the API key using a simple check
                # In a real implementation, this would use the AuthenticationManager's validation
                if len(agent_api_key) > 10:  # Simple length check for demo
                    # Generate agent token
                    token = str(uuid4())
                    self._agent_tokens[agent_id] = token
                    
                    # Add to audit log
                    self._audit_log.append({
                        "action": "authenticate",
                        "agent_id": agent_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "result": "success"
                    })
                    
                    self.logger.info(f"Successfully authenticated agent {agent_id}")
                    return token
                else:
                    # Add to audit log
                    self._audit_log.append({
                        "action": "authenticate",
                        "agent_id": agent_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "result": "failure",
                        "reason": "invalid_api_key"
                    })
                    
                    self.logger.warning(f"Authentication failed for agent {agent_id}")
                    return None
            else:
                # Add to audit log
                self._audit_log.append({
                    "action": "authenticate",
                    "agent_id": agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "failure",
                    "reason": "missing_credentials"
                })
                
                self.logger.warning(f"Authentication failed for agent {agent_id}: missing credentials")
                return None
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "authenticate",
                "agent_id": agent_id,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error authenticating agent {agent_id}: {e}")
            return None
    
    async def verify_agent_token(self, agent_id: str, token: str) -> bool:
        """
        Verify an agent's authentication token.
        
        Args:
            agent_id: ID of the agent
            token: Authentication token to verify
            
        Returns:
            True if token is valid, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Check if token matches stored token
            stored_token = self._agent_tokens.get(agent_id)
            if stored_token and stored_token == token:
                # Add to audit log
                self._audit_log.append({
                    "action": "verify_token",
                    "agent_id": agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "success"
                })
                return True
            else:
                # Add to audit log
                self._audit_log.append({
                    "action": "verify_token",
                    "agent_id": agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "failure",
                    "reason": "invalid_token"
                })
                return False
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "verify_token",
                "agent_id": agent_id,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error verifying token for agent {agent_id}: {e}")
            return False
    
    async def revoke_agent_token(self, agent_id: str) -> bool:
        """
        Revoke an agent's authentication token.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            True if token was revoked successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Remove token
            if agent_id in self._agent_tokens:
                del self._agent_tokens[agent_id]
                
                # Add to audit log
                self._audit_log.append({
                    "action": "revoke_token",
                    "agent_id": agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "success"
                })
                
                self.logger.info(f"Revoked token for agent {agent_id}")
                return True
            else:
                # Add to audit log
                self._audit_log.append({
                    "action": "revoke_token",
                    "agent_id": agent_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "failure",
                    "reason": "no_token_found"
                })
                
                self.logger.warning(f"No token found for agent {agent_id}")
                return False
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "revoke_token",
                "agent_id": agent_id,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error revoking token for agent {agent_id}: {e}")
            return False
    
    async def assign_agent_role(self, agent_id: str, role: str) -> bool:
        """
        Assign a role to an agent.
        
        Args:
            agent_id: ID of the agent
            role: Role to assign
            
        Returns:
            True if role was assigned successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._auth_manager:
            self.logger.error("Authentication manager not available")
            return False
        
        try:
            # For now, accept any role name
            # In a real implementation, this would verify the role with AuthenticationManager
            if not role or not isinstance(role, str):
                self.logger.error(f"Invalid role: {role}")
                return False
            
            # Assign role to agent
            self._agent_roles[agent_id].add(role)
            
            # For now, assign basic permissions based on role
            # In a real implementation, this would get permissions from AuthenticationManager
            role_permissions = self._get_default_permissions_for_role(role)
            if role_permissions:
                self._agent_permissions[agent_id].update(role_permissions)
            
            # Add to audit log
            self._audit_log.append({
                "action": "assign_role",
                "agent_id": agent_id,
                "role": role,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "success"
            })
            
            self.logger.info(f"Assigned role {role} to agent {agent_id}")
            return True
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "assign_role",
                "agent_id": agent_id,
                "role": role,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error assigning role {role} to agent {agent_id}: {e}")
            return False
    
    async def remove_agent_role(self, agent_id: str, role: str) -> bool:
        """
        Remove a role from an agent.
        
        Args:
            agent_id: ID of the agent
            role: Role to remove
            
        Returns:
            True if role was removed successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Remove role from agent
            if role in self._agent_roles[agent_id]:
                self._agent_roles[agent_id].remove(role)
                
                # Update permissions based on role
                role_permissions = self._get_default_permissions_for_role(role)
                if role_permissions:
                    # Remove role permissions, but keep direct permissions
                    for perm in role_permissions:
                        # Only remove if not granted by another role
                        other_roles_have_perm = False
                        for other_role in self._agent_roles[agent_id]:
                            if other_role != role:
                                other_role_perms = self._get_default_permissions_for_role(other_role)
                                if other_role_perms and perm in other_role_perms:
                                    other_roles_have_perm = True
                                    break
                        
                        if not other_roles_have_perm:
                            self._agent_permissions[agent_id].discard(perm)
                
                # Add to audit log
                self._audit_log.append({
                    "action": "remove_role",
                    "agent_id": agent_id,
                    "role": role,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "success"
                })
                
                self.logger.info(f"Removed role {role} from agent {agent_id}")
                return True
            else:
                # Add to audit log
                self._audit_log.append({
                    "action": "remove_role",
                    "agent_id": agent_id,
                    "role": role,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "failure",
                    "reason": "role_not_assigned"
                })
                
                self.logger.warning(f"Role {role} not assigned to agent {agent_id}")
                return False
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "remove_role",
                "agent_id": agent_id,
                "role": role,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error removing role {role} from agent {agent_id}: {e}")
            return False
    
    async def grant_agent_permission(self, agent_id: str, permission: str) -> bool:
        """
        Grant a specific permission to an agent.
        
        Args:
            agent_id: ID of the agent
            permission: Permission to grant
            
        Returns:
            True if permission was granted successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._auth_manager:
            self.logger.error("Authentication manager not available")
            return False
        
        try:
            # For now, accept any permission name
            # In a real implementation, this would verify the permission with AuthenticationManager
            if not permission or not isinstance(permission, str):
                self.logger.error(f"Invalid permission: {permission}")
                return False
            
            # Grant permission to agent
            self._agent_permissions[agent_id].add(permission)
            
            # Add to audit log
            self._audit_log.append({
                "action": "grant_permission",
                "agent_id": agent_id,
                "permission": permission,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "success"
            })
            
            self.logger.info(f"Granted permission {permission} to agent {agent_id}")
            return True
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "grant_permission",
                "agent_id": agent_id,
                "permission": permission,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error granting permission {permission} to agent {agent_id}: {e}")
            return False
    
    async def revoke_agent_permission(self, agent_id: str, permission: str) -> bool:
        """
        Revoke a specific permission from an agent.
        
        Args:
            agent_id: ID of the agent
            permission: Permission to revoke
            
        Returns:
            True if permission was revoked successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Revoke permission from agent
            if permission in self._agent_permissions[agent_id]:
                self._agent_permissions[agent_id].remove(permission)
                
                # Add to audit log
                self._audit_log.append({
                    "action": "revoke_permission",
                    "agent_id": agent_id,
                    "permission": permission,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "success"
                })
                
                self.logger.info(f"Revoked permission {permission} from agent {agent_id}")
                return True
            else:
                # Add to audit log
                self._audit_log.append({
                    "action": "revoke_permission",
                    "agent_id": agent_id,
                    "permission": permission,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": "failure",
                    "reason": "permission_not_granted"
                })
                
                self.logger.warning(f"Permission {permission} not granted to agent {agent_id}")
                return False
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "revoke_permission",
                "agent_id": agent_id,
                "permission": permission,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error revoking permission {permission} from agent {agent_id}: {e}")
            return False
    
    async def check_agent_permission(self, agent_id: str, permission: str) -> bool:
        """
        Check if an agent has a specific permission.
        
        Args:
            agent_id: ID of the agent
            permission: Permission to check
            
        Returns:
            True if agent has permission, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Check if agent has permission
            has_permission = permission in self._agent_permissions.get(agent_id, set())
            
            # Add to audit log
            self._audit_log.append({
                "action": "check_permission",
                "agent_id": agent_id,
                "permission": permission,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "success" if has_permission else "failure"
            })
            
            return has_permission
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "check_permission",
                "agent_id": agent_id,
                "permission": permission,
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error checking permission {permission} for agent {agent_id}: {e}")
            return False
    
    async def authorize_agent_to_agent(self, source_agent_id: str, target_agent_id: str,
                                  action: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Authorize one agent to perform an action on another agent.
        
        Args:
            source_agent_id: ID of the agent requesting the action
            target_agent_id: ID of the agent on which the action will be performed
            action: Action to be performed
            context: Optional context for the authorization
            
        Returns:
            True if authorization is granted, False otherwise
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._auth_manager:
            self.logger.error("Authentication manager not available")
            return False
        
        try:
            # Check if source agent has permission to perform action
            permission = f"agent:{action}"
            if not await self.check_agent_permission(source_agent_id, permission):
                self.logger.warning(f"Agent {source_agent_id} lacks permission {permission}")
                return False
            
            # Check if target agent allows the action
            target_permission = f"agent:allow:{action}"
            if not await self.check_agent_permission(target_agent_id, target_permission):
                self.logger.warning(f"Agent {target_agent_id} does not allow action {action}")
                return False
            
            # Verify context-specific constraints
            if context:
                # For now, skip context-specific authorization rules
                # In a real implementation, this would get rules from AuthenticationManager
                pass
            
            # Add to audit log
            self._audit_log.append({
                "action": "authorize_agent_to_agent",
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
                "action": action,
                "context": context or {},
                "timestamp": datetime.utcnow().isoformat(),
                "result": "success"
            })
            
            self.logger.info(f"Authorized agent {source_agent_id} to perform {action} on agent {target_agent_id}")
            return True
        except Exception as e:
            # Add to audit log
            self._audit_log.append({
                "action": "authorize_agent_to_agent",
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
                "action": action,
                "context": context or {},
                "timestamp": datetime.utcnow().isoformat(),
                "result": "error",
                "error": str(e)
            })
            
            self.logger.error(f"Error authorizing agent {source_agent_id} to perform {action} on agent {target_agent_id}: {e}")
            return False
    
    async def _apply_authorization_rule(self, rule: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Apply an authorization rule to a context.
        
        Args:
            rule: Authorization rule to apply
            context: Context to check against the rule
            
        Returns:
            True if rule passes, False otherwise
        """
        try:
            # Get rule type
            rule_type = rule.get("type")
            
            if rule_type == "time_constraint":
                # Check if current time is within allowed time window
                current_time = datetime.utcnow().time()
                start_time = datetime.strptime(rule.get("start_time", "00:00"), "%H:%M").time()
                end_time = datetime.strptime(rule.get("end_time", "23:59"), "%H:%M").time()
                
                if start_time <= end_time:
                    # Normal time window (e.g., 09:00 to 17:00)
                    return start_time <= current_time <= end_time
                else:
                    # Wrapping time window (e.g., 22:00 to 06:00)
                    return current_time >= start_time or current_time <= end_time
            
            elif rule_type == "resource_limit":
                # Check if resource usage is within limits
                resource_type = rule.get("resource_type")
                max_usage = rule.get("max_usage", 1.0)
                current_usage = context.get("resource_usage", {}).get(resource_type, 0.0)
                
                return current_usage <= max_usage
            
            elif rule_type == "capability_requirement":
                # Check if required capabilities are present
                required_capabilities = rule.get("required_capabilities", [])
                agent_capabilities = context.get("capabilities", [])
                
                return all(cap in agent_capabilities for cap in required_capabilities)
            
            elif rule_type == "role_requirement":
                # Check if required roles are present
                required_roles = rule.get("required_roles", [])
                agent_roles = context.get("roles", [])
                
                return all(role in agent_roles for role in required_roles)
            
            # Default: allow if rule type is unknown
            return True
        except Exception as e:
            self.logger.error(f"Error applying authorization rule: {e}")
            return False
    
    def _get_default_permissions_for_role(self, role: str) -> Set[str]:
        """
        Get default permissions for a role.
        
        Args:
            role: Role name
            
        Returns:
            Set of permissions for the role
        """
        # Define default permissions for common roles
        default_role_permissions = {
            "admin": {
                "agent:register",
                "agent:deregister",
                "agent:update",
                "agent:read",
                "agent:execute",
                "agent:manage",
                "permission:grant",
                "permission:revoke",
                "role:assign",
                "role:remove",
                "system:configure",
                "system:monitor"
            },
            "operator": {
                "agent:register",
                "agent:update",
                "agent:read",
                "agent:execute",
                "system:monitor"
            },
            "user": {
                "agent:read",
                "agent:execute"
            },
            "monitor": {
                "agent:read",
                "system:monitor"
            }
        }
        
        return default_role_permissions.get(role, set())
    
    async def get_audit_log(self, agent_id: Optional[str] = None, action: Optional[str] = None,
                         start_time: Optional[datetime] = None, end_time: Optional[datetime] = None,
                         limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get audit log entries with optional filtering.
        
        Args:
            agent_id: Optional agent ID to filter by
            action: Optional action to filter by
            start_time: Optional start time for filtering
            end_time: Optional end time for filtering
            limit: Maximum number of entries to return
            
        Returns:
            List of audit log entries
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get all audit log entries
            entries = list(self._audit_log)
            
            # Filter by agent ID
            if agent_id:
                entries = [entry for entry in entries if entry.get("agent_id") == agent_id]
            
            # Filter by action
            if action:
                entries = [entry for entry in entries if entry.get("action") == action]
            
            # Filter by time range
            if start_time:
                entries = [entry for entry in entries if
                           datetime.fromisoformat(entry.get("timestamp", "")) >= start_time]
            
            if end_time:
                entries = [entry for entry in entries if
                           datetime.fromisoformat(entry.get("timestamp", "")) <= end_time]
            
            # Sort by timestamp (newest first) and limit
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]
        except Exception as e:
            self.logger.error(f"Error getting audit log: {e}")
            return []
