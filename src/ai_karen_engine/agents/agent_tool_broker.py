"""
Enhanced Agent Tool Broker service for managing agent tools with deep integration
to Karen's Tool Registry and advanced security features.

.. deprecated::
    The legacy tool broker is deprecated. Tool access is now governed by
    ``ai_karen_engine.agent_medusa`` and ``ai_karen_engine.core.tools``.
"""

import asyncio
import logging
import time
import threading
import warnings
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from datetime import datetime, timedelta
from enum import Enum

warnings.warn(
    "ai_karen_engine.agents.agent_tool_broker is deprecated. "
    "Use ai_karen_engine.agent_medusa and ai_karen_engine.core.tools instead.",
    DeprecationWarning,
    stacklevel=2,
)
from uuid import uuid4
from collections import defaultdict

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from .internal import agent_schemas
from .internal import agent_validation
from .internal import agent_metrics

logger = logging.getLogger(__name__)


class ToolStatus(str, Enum):
    """Tool status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    BLACKLISTED = "blacklisted"


class AccessDecision(str, Enum):
    """Access decision enumeration."""
    ALLOW = "allow"
    DENY = "deny"
    CHALLENGE = "challenge"
    REQUIRE_MFA = "require_mfa"


class SecurityContext(str, Enum):
    """Security context enumeration."""
    NORMAL = "normal"
    ELEVATED = "elevated"
    RESTRICTED = "restricted"
    ISOLATED = "isolated"


class AgentToolBroker(BaseService):
    """
    Enhanced Agent Tool Broker service for managing agent tools with deep integration
    to Karen's Tool Registry and advanced security features.
    
    This service provides comprehensive capabilities for agents to discover, access, and manage
    tools with secure access control, usage monitoring, and intelligent capability matching.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_tool_broker"))
        self._initialized = False
        
        # Core services
        self._validation_service: Optional[agent_validation.AgentValidation] = None
        self._metrics_service: Optional[agent_metrics.AgentMetrics] = None
        
        # Tool registry
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_categories: Dict[str, Set[str]] = defaultdict(set)
        self._tool_capabilities: Dict[str, Set[str]] = defaultdict(set)
        self._tool_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._tool_versions: Dict[str, Dict[str, Any]] = {}
        
        # Karen's Tool Registry integration
        self._karen_registry_client = None
        self._registry_sync_enabled = True
        self._last_sync_time = None
        self._sync_interval_minutes = 30
        self._registry_tools: Dict[str, Dict[str, Any]] = {}
        
        # Security and permissions
        self._agent_permissions: Dict[str, Dict[str, agent_schemas.PermissionLevel]] = {}
        self._role_permissions: Dict[str, Dict[str, Set[str]]] = {}
        self._agent_contexts: Dict[str, SecurityContext] = {}
        self._whitelist: Set[str] = set()
        self._blacklist: Set[str] = set()
        self._session_tokens: Dict[str, str] = {}
        
        # Access policies
        self._access_policies: Dict[str, Dict[str, Any]] = {}
        self._policy_rules: Dict[str, List[Dict[str, Any]]] = {}
        
        # Usage monitoring and auditing
        self._tool_usage_stats: Dict[str, Dict[str, Any]] = {}
        self._agent_usage_stats: Dict[str, Dict[str, Any]] = {}
        self._access_log: List[Dict[str, Any]] = []
        self._security_events: List[Dict[str, Any]] = []
        self._anomaly_scores: Dict[str, float] = {}
        self._suspicious_agents: Set[str] = set()
        
        # Tool execution
        self._execution_queue: List[Dict[str, Any]] = []
        self._active_executions: Dict[str, Dict[str, Any]] = {}
        self._execution_history: List[Dict[str, Any]] = []
        
        # Configuration
        self._default_permission_level = agent_schemas.PermissionLevel.READ
        self._require_mfa_for_admin = True
        self._enable_rate_limiting = True
        self._enable_anomaly_detection = True
        self._max_denied_attempts = 5
        self._denied_attempt_window_minutes = 15
        self._access_cache_ttl_minutes = 30
        self._rate_limit_window_minutes = 5
        self._max_requests_per_window = 100
        self._anomaly_threshold = 0.7
        self._mfa_timeout_seconds = 300
        self._session_timeout_hours = 24
        self._audit_retention_days = 90
        
        # Locks for thread safety
        self._tools_lock = threading.RLock()
        self._permissions_lock = threading.RLock()
        self._usage_lock = threading.RLock()
        self._execution_lock = threading.RLock()
        self._audit_lock = threading.RLock()
        self._registry_lock = threading.RLock()
        
        # Background tasks
        self._registry_sync_task_obj: Optional[asyncio.Task] = None
        self._execution_processor_obj: Optional[asyncio.Task] = None
        self._audit_log_processor_obj: Optional[asyncio.Task] = None
        self._security_monitor_obj: Optional[asyncio.Task] = None
        self._usage_stats_aggregator_obj: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """Initialize the enhanced agent tool broker."""
        if self._initialized:
            return
            
        logger.info("Initializing Enhanced Agent Tool Broker service")
        
        try:
            # Initialize internal services
            self._validation_service = agent_validation.AgentValidation(config=ServiceConfig(name="tool_broker_validation"))
            await self._validation_service.initialize()
            
            self._metrics_service = agent_metrics.AgentMetrics(config=ServiceConfig(name="tool_broker_metrics"))
            await self._metrics_service.initialize()
            
            # Load configuration
            self._load_configuration()
            
            # Initialize Karen's Tool Registry integration
            await self._initialize_karen_registry_integration()
            
            # Start background tasks
            self._registry_sync_task_obj = asyncio.create_task(self._registry_sync_task())
            self._execution_processor_obj = asyncio.create_task(self._execution_processor())
            self._audit_log_processor_obj = asyncio.create_task(self._audit_log_processor())
            self._security_monitor_obj = asyncio.create_task(self._security_monitor())
            self._usage_stats_aggregator_obj = asyncio.create_task(self._usage_stats_aggregator())
            
            self._initialized = True
            logger.info("Enhanced Agent Tool Broker initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Enhanced Agent Tool Broker: {e}")
            raise
    
    def _load_configuration(self) -> None:
        """Load tool broker configuration."""
        # Load from service configuration
        config = self.config.data.get("tool_broker", {})
        
        # Permission settings
        self._default_permission_level = agent_schemas.PermissionLevel(config.get("default_permission_level", "read"))
        self._require_mfa_for_admin = config.get("require_mfa_for_admin", True)
        
        # Security settings
        self._enable_rate_limiting = config.get("enable_rate_limiting", True)
        self._enable_anomaly_detection = config.get("enable_anomaly_detection", True)
        
        # Access policy settings
        self._max_denied_attempts = config.get("max_denied_attempts", 5)
        self._denied_attempt_window_minutes = config.get("denied_attempt_window_minutes", 15)
        
        # Cache and rate limiting settings
        self._access_cache_ttl_minutes = config.get("access_cache_ttl_minutes", 30)
        self._rate_limit_window_minutes = config.get("rate_limit_window_minutes", 5)
        self._max_requests_per_window = config.get("max_requests_per_window", 100)
        
        # Anomaly detection settings
        self._anomaly_threshold = config.get("anomaly_threshold", 0.7)
        
        # MFA settings
        self._mfa_timeout_seconds = config.get("mfa_timeout_seconds", 300)
        
        # Session settings
        self._session_timeout_hours = config.get("session_timeout_hours", 24)
        
        # Audit settings
        self._audit_retention_days = config.get("audit_retention_days", 90)
        
        # Registry settings
        self._registry_sync_enabled = config.get("registry_sync_enabled", True)
        self._sync_interval_minutes = config.get("sync_interval_minutes", 30)
        
        # Load whitelist/blacklist if configured
        whitelist = config.get("whitelist", [])
        self._whitelist = set(whitelist)
        
        blacklist = config.get("blacklist", [])
        self._blacklist = set(blacklist)
        
        # Load access policies
        policies = config.get("access_policies", {})
        for policy_name, policy_config in policies.items():
            self._access_policies[policy_name] = policy_config.copy()
            
        logger.info(f"Loaded tool broker configuration with {len(self._access_policies)} policies")
    
    async def _initialize_karen_registry_integration(self) -> None:
        """Initialize integration with Karen's Tool Registry."""
        try:
            # In a real implementation, this would initialize a client to Karen's Tool Registry
            # For now, we'll simulate the integration
            
            self._karen_registry_client = {
                "status": "connected",
                "last_sync": None,
                "tools_count": 0
            }
            
            logger.info("Initialized Karen's Tool Registry integration")
            
        except Exception as e:
            logger.error(f"Failed to initialize Karen's Tool Registry integration: {e}")
            self._registry_sync_enabled = False
    
    async def start(self) -> None:
        """Start the enhanced agent tool broker."""
        logger.info("Enhanced Agent Tool Broker started")
    
    async def stop(self) -> None:
        """Stop the enhanced agent tool broker."""
        logger.info("Enhanced Agent Tool Broker stopped")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of the enhanced agent tool broker."""
        base_health = {
            "service": "agent_tool_broker",
            "timestamp": datetime.utcnow().isoformat(),
            "initialized": self._initialized,
            "tools_count": len(self._tools),
            "agents_with_permissions": len(self._agent_permissions),
            "active_sessions": len(self._session_tokens),
            "whitelist_size": len(self._whitelist),
            "blacklist_size": len(self._blacklist),
            "registry_sync_enabled": self._registry_sync_enabled,
            "registry_tools_count": len(self._registry_tools),
            "execution_queue_size": len(self._execution_queue),
            "active_executions_count": len(self._active_executions)
        }
        
        # Check health of dependent services
        if self._validation_service:
            base_health["validation_service"] = "healthy" if await self._validation_service.health_check() else "unhealthy"
        
        if self._metrics_service:
            base_health["metrics_service"] = "healthy" if await self._metrics_service.health_check() else "unhealthy"
        
        # Determine overall status
        unhealthy_components = [
            component for component, status in base_health.items()
            if component.endswith("_service") and status == "unhealthy"
        ]
        
        if unhealthy_components:
            base_health["status"] = "degraded"
            base_health["unhealthy_components"] = unhealthy_components
        else:
            base_health["status"] = "healthy"
        
        return base_health
    
    async def register_tool(
        self, 
        tool_id: str, 
        tool_name: str, 
        description: str,
        input_schema: Dict[str, Any],
        execution_handler: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a new tool with the broker.
        
        Args:
            tool_id: Unique identifier for the tool
            tool_name: Human-readable name for the tool
            description: Description of what the tool does
            input_schema: Schema for tool input
            execution_handler: Reference to the function that executes the tool
            capabilities: List of capabilities provided by the tool
            metadata: Additional metadata about the tool
            
        Returns:
            True if registration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._tools_lock:
            if tool_id in self._tools:
                logger.warning(f"Tool {tool_id} already registered, updating registration")
            
            self._tools[tool_id] = {
                "tool_id": tool_id,
                "tool_name": tool_name,
                "description": description,
                "input_schema": input_schema,
                "execution_handler": execution_handler,
                "capabilities": capabilities,
                "metadata": metadata or {},
                "registered_at": datetime.utcnow().isoformat(),
                "status": "active"
            }
            
            # Initialize usage stats for the tool
            if tool_id not in self._tool_usage_stats:
                self._tool_usage_stats[tool_id] = {
                    "usage_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "last_used": None,
                    "average_execution_time": 0.0
                }
            
            logger.info(f"Tool {tool_id} registered successfully")
            return True
    
    async def unregister_tool(self, tool_id: str) -> bool:
        """
        Unregister a tool from the broker.
        
        Args:
            tool_id: Unique identifier of the tool to unregister
            
        Returns:
            True if unregistration was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._tools_lock:
            if tool_id not in self._tools:
                logger.warning(f"Tool {tool_id} not found in registry")
                return False
            
            del self._tools[tool_id]
            
            # Remove usage stats for the tool
            self._tool_usage_stats.pop(tool_id, None)
            
            # Remove tool from all agent permissions
            for agent_id, tools in self._agent_permissions.items():
                if tool_id in tools:
                    del tools[tool_id]
            
            logger.info(f"Tool {tool_id} unregistered successfully")
            return True
    
    async def grant_agent_tool_access(
        self, 
        agent_id: str, 
        tool_id: str
    ) -> bool:
        """
        Grant an agent access to a tool.
        
        Args:
            agent_id: Unique identifier of the agent
            tool_id: Unique identifier of the tool
            
        Returns:
            True if access was granted, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._permissions_lock:
            if tool_id not in self._tools:
                logger.warning(f"Tool {tool_id} not found in registry")
                return False
            
            if agent_id not in self._agent_permissions:
                self._agent_permissions[agent_id] = {}
            
            if tool_id not in self._agent_permissions[agent_id]:
                self._agent_permissions[agent_id][tool_id] = self._default_permission_level
                logger.info(f"Granted agent {agent_id} access to tool {tool_id}")
                return True
            
            return False
    
    async def revoke_agent_tool_access(
        self, 
        agent_id: str, 
        tool_id: str
    ) -> bool:
        """
        Revoke an agent's access to a tool.
        
        Args:
            agent_id: Unique identifier of the agent
            tool_id: Unique identifier of the tool
            
        Returns:
            True if access was revoked, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._permissions_lock:
            if agent_id not in self._agent_permissions:
                return False
            
            if tool_id in self._agent_permissions[agent_id]:
                del self._agent_permissions[agent_id][tool_id]
                logger.info(f"Revoked agent {agent_id} access to tool {tool_id}")
                return True
            
            return False
    
    async def get_agent_tools(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Get all tools accessible to an agent.
        
        Args:
            agent_id: Unique identifier of the agent
            
        Returns:
            List of tool information
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._permissions_lock:
            if agent_id not in self._agent_permissions:
                return []
            
            tool_ids = list(self._agent_permissions[agent_id].keys())
            tools = []
            
            for tool_id in tool_ids:
                if tool_id in self._tools:
                    tools.append(self._tools[tool_id].copy())
            
            return tools
    
    async def list_tools(self, capability: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all tools or tools with a specific capability.
        
        Args:
            capability: Optional filter for tool capability
            
        Returns:
            List of tool information
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._tools_lock:
            tools = list(self._tools.values())
            
            if capability:
                tools = [tool for tool in tools if capability in tool["capabilities"]]
                
            return tools
    
    async def execute_tool(
        self, 
        agent_id: str, 
        tool_id: str, 
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool on behalf of an agent.
        
        Args:
            agent_id: Unique identifier of the agent
            tool_id: Unique identifier of the tool
            parameters: Parameters for tool execution
            
        Returns:
            Tool execution result
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._execution_lock:
            # Check if agent has access to the tool
            if agent_id not in self._agent_permissions:
                return {
                    "status": "error",
                    "message": f"Agent {agent_id} has no tool access",
                    "tool_id": tool_id
                }
            
            if tool_id not in self._agent_permissions[agent_id]:
                return {
                    "status": "error",
                    "message": f"Agent {agent_id} does not have access to tool {tool_id}",
                    "tool_id": tool_id
                }
            
            # Check if tool exists
            if tool_id not in self._tools:
                return {
                    "status": "error",
                    "message": f"Tool {tool_id} not found",
                    "tool_id": tool_id
                }
            
            # Get tool information
            tool = self._tools[tool_id]
            
            # Update usage stats
            stats = self._tool_usage_stats[tool_id]
            stats["usage_count"] += 1
            stats["last_used"] = datetime.utcnow().isoformat()
            
            # In a real implementation, we would execute the tool here
            # For now, we'll simulate execution
            try:
                start_time = datetime.utcnow()
                
                # Simulate tool execution
                result = await self._simulate_tool_execution(tool, parameters)
                
                end_time = datetime.utcnow()
                execution_time = (end_time - start_time).total_seconds()
                
                # Update usage stats
                stats["success_count"] += 1
                stats["average_execution_time"] = (
                    (stats["average_execution_time"] * (stats["success_count"] - 1) + execution_time) / 
                    stats["success_count"]
                )
                
                return {
                    "status": "success",
                    "tool_id": tool_id,
                    "result": result,
                    "execution_time_ms": execution_time * 1000
                }
                
            except Exception as e:
                # Update error stats
                stats["error_count"] += 1
                
                logger.error(f"Tool {tool_id} execution failed: {e}")
                return {
                    "status": "error",
                    "tool_id": tool_id,
                    "error": str(e)
                }
    
    async def _simulate_tool_execution(
        self, 
        tool: Dict[str, Any], 
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Simulate tool execution.
        
        Args:
            tool: Tool information
            parameters: Tool execution parameters
            
        Returns:
            Tool execution result
        """
        # This is a placeholder for actual tool execution
        # In a real implementation, this would call the tool's execution handler
        
        tool_name = tool["tool_name"]
        
        logger.info(f"Executing tool {tool_name} with parameters {parameters}")
        
        # Simulate execution delay
        await asyncio.sleep(0.05)
        
        # Return a mock result
        return {
            "output": f"Tool {tool_name} executed successfully",
            "processed_parameters": parameters
        }
    
    async def get_tool_usage_stats(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        Get usage statistics for a tool.
        
        Args:
            tool_id: Unique identifier of the tool
            
        Returns:
            Tool usage statistics or None if not found
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._usage_lock:
            return self._tool_usage_stats.get(tool_id)
    
    async def get_tool_info(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific tool.
        
        Args:
            tool_id: Unique identifier of the tool
            
        Returns:
            Tool information if found, None otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._tools_lock:
            if tool_id in self._tools:
                return self._tools[tool_id].copy()
            return None
    
    async def _registry_sync_task(self) -> None:
        """Background task for synchronizing with Karen's Tool Registry."""
        while True:
            try:
                if not self._initialized or not self._registry_sync_enabled:
                    await asyncio.sleep(1)
                    continue
                
                # Check if sync is needed
                now = datetime.utcnow()
                last_sync = self._last_sync_time
                
                if not last_sync or (now - last_sync).total_seconds() > self._sync_interval_minutes * 60:
                    await self._sync_with_karen_registry()
                    self._last_sync_time = now
                
                # Sleep for a minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in registry sync task: {e}")
                await asyncio.sleep(60)
    
    async def _sync_with_karen_registry(self) -> None:
        """Synchronize tools with Karen's Tool Registry."""
        try:
            with self._registry_lock:
                # In a real implementation, this would fetch tools from Karen's Tool Registry
                # For now, we'll simulate the sync
                
                # Simulate fetching tools from registry
                registry_tools = {}
                
                # Update local registry tools
                self._registry_tools = registry_tools
                
                # Update client status
                if self._karen_registry_client:
                    self._karen_registry_client["last_sync"] = datetime.utcnow().isoformat()
                    self._karen_registry_client["tools_count"] = len(registry_tools)
                
                logger.info(f"Synced with Karen's Tool Registry, got {len(registry_tools)} tools")
                
        except Exception as e:
            logger.error(f"Failed to sync with Karen's Tool Registry: {e}")
            if self._karen_registry_client:
                self._karen_registry_client["status"] = "error"
    
    async def _execution_processor(self) -> None:
        """Background task for processing tool executions."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Process execution queue
                with self._execution_lock:
                    if self._execution_queue:
                        execution = self._execution_queue.pop(0)
                        execution_id = execution["execution_id"]
                        
                        # Move to active executions
                        self._active_executions[execution_id] = execution
                        
                        # Start execution in background
                        asyncio.create_task(self._execute_tool_task(execution))
                
                # Sleep for a short time
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in execution processor: {e}")
                await asyncio.sleep(1)
    
    async def _execute_tool_task(self, execution: Dict[str, Any]) -> None:
        """Execute a tool task."""
        execution_id = execution["execution_id"]
        agent_id = execution["agent_id"]
        tool_id = execution["tool_id"]
        parameters = execution["parameters"]
        
        try:
            # Check if agent has access to the tool
            if agent_id not in self._agent_permissions or tool_id not in self._agent_permissions[agent_id]:
                result = {
                    "status": "error",
                    "message": f"Agent {agent_id} does not have access to tool {tool_id}",
                    "tool_id": tool_id
                }
            else:
                # Check if tool exists
                if tool_id not in self._tools:
                    result = {
                        "status": "error",
                        "message": f"Tool {tool_id} not found",
                        "tool_id": tool_id
                    }
                else:
                    # Get tool information
                    tool = self._tools[tool_id]
                    
                    # Update usage stats
                    with self._usage_lock:
                        if tool_id not in self._tool_usage_stats:
                            self._tool_usage_stats[tool_id] = {
                                "usage_count": 0,
                                "success_count": 0,
                                "error_count": 0,
                                "last_used": None,
                                "average_execution_time": 0.0
                            }
                        
                        stats = self._tool_usage_stats[tool_id]
                        stats["usage_count"] += 1
                        stats["last_used"] = datetime.utcnow().isoformat()
                    
                    # Execute tool
                    try:
                        start_time = datetime.utcnow()
                        
                        # Simulate tool execution
                        tool_result = await self._simulate_tool_execution(tool, parameters)
                        
                        end_time = datetime.utcnow()
                        execution_time = (end_time - start_time).total_seconds()
                        
                        # Update usage stats
                        with self._usage_lock:
                            stats["success_count"] += 1
                            stats["average_execution_time"] = (
                                (stats["average_execution_time"] * (stats["success_count"] - 1) + execution_time) /
                                stats["success_count"]
                            )
                        
                        result = {
                            "status": "success",
                            "tool_id": tool_id,
                            "result": tool_result,
                            "execution_time_ms": execution_time * 1000
                        }
                        
                    except Exception as e:
                        # Update error stats
                        with self._usage_lock:
                            stats["error_count"] += 1
                        
                        logger.error(f"Tool {tool_id} execution failed: {e}")
                        result = {
                            "status": "error",
                            "tool_id": tool_id,
                            "error": str(e)
                        }
            
            # Store result
            with self._execution_lock:
                if execution_id in self._active_executions:
                    self._active_executions[execution_id]["result"] = result
                    self._active_executions[execution_id]["completed_at"] = datetime.utcnow().isoformat()
                    self._active_executions[execution_id]["status"] = "completed"
                    
                    # Move to history
                    self._execution_history.append(self._active_executions[execution_id])
                    
                    # Remove from active executions
                    del self._active_executions[execution_id]
                    
                    # Keep only last 1000 executions in history
                    if len(self._execution_history) > 1000:
                        self._execution_history = self._execution_history[-1000:]
            
        except Exception as e:
            logger.error(f"Error executing tool task {execution_id}: {e}")
            
            # Store error result
            with self._execution_lock:
                if execution_id in self._active_executions:
                    self._active_executions[execution_id]["result"] = {
                        "status": "error",
                        "error": str(e)
                    }
                    self._active_executions[execution_id]["completed_at"] = datetime.utcnow().isoformat()
                    self._active_executions[execution_id]["status"] = "failed"
                    
                    # Move to history
                    self._execution_history.append(self._active_executions[execution_id])
                    
                    # Remove from active executions
                    del self._active_executions[execution_id]
    
    async def _audit_log_processor(self) -> None:
        """Background task for processing audit logs."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Process audit logs
                with self._audit_lock:
                    # Keep only recent audit logs
                    cutoff_time = datetime.utcnow() - timedelta(days=self._audit_retention_days)
                    self._access_log = [
                        event for event in self._access_log
                        if datetime.fromisoformat(event.get("timestamp", "")) >= cutoff_time
                    ]
                    
                    # Keep only recent security events
                    self._security_events = [
                        event for event in self._security_events
                        if datetime.fromisoformat(event.get("timestamp", "")) >= cutoff_time
                    ]
                
                # Sleep for an hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error in audit log processor: {e}")
                await asyncio.sleep(3600)
    
    async def _security_monitor(self) -> None:
        """Background task for monitoring security events."""
        while True:
            try:
                if not self._initialized or not self._enable_anomaly_detection:
                    await asyncio.sleep(1)
                    continue
                
                # Check for suspicious agents based on anomaly scores
                suspicious_agents = set()
                
                with self._audit_lock:
                    for agent_id, score in self._anomaly_scores.items():
                        if score > self._anomaly_threshold:
                            suspicious_agents.add(agent_id)
                
                # Update suspicious agents set
                self._suspicious_agents.update(suspicious_agents)
                
                # Log security events for highly anomalous agents
                for agent_id in suspicious_agents:
                    with self._audit_lock:
                        self._security_events.append({
                            "event_type": "anomaly_detected",
                            "agent_id": agent_id,
                            "anomaly_score": self._anomaly_scores.get(agent_id, 0.0),
                            "timestamp": datetime.utcnow().isoformat(),
                            "severity": "high" if self._anomaly_scores.get(agent_id, 0.0) > 0.9 else "medium"
                        })
                
                if suspicious_agents:
                    logger.warning(f"Detected anomalous access patterns for {len(suspicious_agents)} agents")
                
                # Sleep for 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error in security monitor: {e}")
                await asyncio.sleep(300)
    
    async def _usage_stats_aggregator(self) -> None:
        """Background task for aggregating usage statistics."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue
                
                # Aggregate tool usage statistics
                with self._usage_lock:
                    for tool_id, stats in self._tool_usage_stats.items():
                        # Calculate additional statistics
                        if stats["usage_count"] > 0:
                            stats["success_rate"] = stats["success_count"] / stats["usage_count"]
                            stats["error_rate"] = stats["error_count"] / stats["usage_count"]
                        else:
                            stats["success_rate"] = 0.0
                            stats["error_rate"] = 0.0
                
                # Aggregate agent usage statistics
                with self._usage_lock:
                    for agent_id, permissions in self._agent_permissions.items():
                        if agent_id not in self._agent_usage_stats:
                            self._agent_usage_stats[agent_id] = {
                                "tool_count": 0,
                                "execution_count": 0,
                                "success_count": 0,
                                "error_count": 0,
                                "last_used": None
                            }
                        
                        agent_stats = self._agent_usage_stats[agent_id]
                        agent_stats["tool_count"] = len(permissions)
                
                # Sleep for a minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in usage stats aggregator: {e}")
                await asyncio.sleep(60)
    
    async def _initialize_service(self) -> None:
        """Initialize agent tool broker service-specific resources."""
        # This is called by the BaseService.initialize() method
        pass
    
    async def _start_service(self) -> None:
        """Start agent tool broker service-specific resources."""
        # This is called by the BaseService.start() method
        pass
    
    async def _stop_service(self) -> None:
        """Stop agent tool broker service-specific resources."""
        # This is called by the BaseService.stop() method
        # Cancel background tasks
        if hasattr(self, '_registry_sync_task_obj') and self._registry_sync_task_obj:
            self._registry_sync_task_obj.cancel()
        if hasattr(self, '_execution_processor_obj') and self._execution_processor_obj:
            self._execution_processor_obj.cancel()
        if hasattr(self, '_audit_log_processor_obj') and self._audit_log_processor_obj:
            self._audit_log_processor_obj.cancel()
        if hasattr(self, '_security_monitor_obj') and self._security_monitor_obj:
            self._security_monitor_obj.cancel()
        if hasattr(self, '_usage_stats_aggregator_obj') and self._usage_stats_aggregator_obj:
            self._usage_stats_aggregator_obj.cancel()
    
    async def _health_check_service(self) -> Dict[str, Any]:
        """Check health of agent tool broker service-specific resources."""
        # This is called by the BaseService.health_check() method
        return {
            "healthy": self._initialized,
            "background_tasks": {
                "registry_sync": hasattr(self, '_registry_sync_task_obj') and self._registry_sync_task_obj and not self._registry_sync_task_obj.done(),
                "execution_processor": hasattr(self, '_execution_processor_obj') and self._execution_processor_obj and not self._execution_processor_obj.done(),
                "audit_log_processor": hasattr(self, '_audit_log_processor_obj') and self._audit_log_processor_obj and not self._audit_log_processor_obj.done(),
                "security_monitor": hasattr(self, '_security_monitor_obj') and self._security_monitor_obj and not self._security_monitor_obj.done(),
                "usage_stats_aggregator": hasattr(self, '_usage_stats_aggregator_obj') and self._usage_stats_aggregator_obj and not self._usage_stats_aggregator_obj.done()
            }
        }