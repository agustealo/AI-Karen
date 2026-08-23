"""
Tool Abstraction Service.

This service provides a unified interface for all tools and external service integrations,
creating a standardized way to discover, validate, and execute tools across the AI Karen system.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, Type, get_type_hints
from dataclasses import dataclass, field
from enum import Enum
import uuid
import inspect

try:
    from pydantic import BaseModel, ConfigDict, Field, validator, create_model
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field, validator, create_model

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Tool category enumeration."""
    CORE = "core"
    TIME = "time"
    WEATHER = "weather"
    COMMUNICATION = "communication"
    DATABASE = "database"
    SYSTEM = "system"
    ANALYTICS = "analytics"
    MEMORY = "memory"
    PLUGIN = "plugin"
    CUSTOM = "custom"


class ToolStatus(str, Enum):
    """Tool status enumeration."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class ToolParameter:
    """Tool parameter specification."""
    name: str
    type: Type
    description: str
    required: bool = True
    default: Any = None
    validation_rules: Optional[Dict[str, Any]] = None


@dataclass
class ToolMetadata:
    """Tool metadata specification."""
    name: str
    description: str
    category: ToolCategory
    version: str = "1.0.0"
    author: str = "AI Karen"
    parameters: List[ToolParameter] = field(default_factory=list)
    return_type: Type = str
    examples: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    requires_auth: bool = False
    rate_limit: Optional[int] = None  # requests per minute
    timeout: int = 30  # seconds
    status: ToolStatus = ToolStatus.AVAILABLE


class ToolInput(BaseModel):
    """Tool input model."""
    tool_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    user_context: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ToolOutput(BaseModel):
    """Tool output model."""
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float
    metadata: Optional[Dict[str, Any]] = None
    request_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ToolValidationError(Exception):
    """Tool validation error."""
    pass


class ToolExecutionError(Exception):
    """Tool execution error."""
    pass


class BaseTool(ABC):
    """
    Abstract base class for all tools.
    
    All tools must inherit from this class and implement the required methods.
    """
    
    def __init__(self):
        """Initialize the tool."""
        self._metadata: Optional[ToolMetadata] = None
        self._execution_count = 0
        self._last_execution = None
        self._rate_limit_tracker = {}
    
    @property
    def metadata(self) -> ToolMetadata:
        """Get tool metadata."""
        if self._metadata is None:
            self._metadata = self._create_metadata()
        return self._metadata
    
    @abstractmethod
    def _create_metadata(self) -> ToolMetadata:
        """Create tool metadata. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        """Execute the tool with given parameters. Must be implemented by subclasses."""
        pass
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """
        Execute the tool with validation and error handling.
        
        Args:
            tool_input: Tool input containing parameters and context
            
        Returns:
            Tool output with result or error
        """
        start_time = time.time()
        
        try:
            # Check rate limiting
            if not self._check_rate_limit(tool_input.user_id):
                raise ToolExecutionError(f"Rate limit exceeded for tool {self.metadata.name}")
            
            # Validate input parameters
            validated_params = self.validate_input(tool_input.parameters)
            
            # Execute the tool
            result = await self._execute(validated_params, tool_input.user_context)
            
            # Validate output
            validated_result = self.validate_output(result)
            
            # Update execution tracking
            self._execution_count += 1
            self._last_execution = datetime.utcnow()
            
            execution_time = time.time() - start_time
            
            return ToolOutput(
                success=True,
                result=validated_result,
                execution_time=execution_time,
                request_id=tool_input.request_id,
                metadata={
                    "tool_name": self.metadata.name,
                    "execution_count": self._execution_count,
                    "category": self.metadata.category.value
                }
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_message = str(e)
            
            logger.error(f"Tool {self.metadata.name} execution failed: {error_message}")
            
            return ToolOutput(
                success=False,
                result=None,
                error=error_message,
                execution_time=execution_time,
                request_id=tool_input.request_id,
                metadata={
                    "tool_name": self.metadata.name,
                    "error_type": type(e).__name__
                }
            )
    
    def validate_input(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate input parameters against tool metadata.
        
        Args:
            parameters: Input parameters to validate
            
        Returns:
            Validated parameters
            
        Raises:
            ToolValidationError: If validation fails
        """
        validated = {}
        
        # Check required parameters
        for param in self.metadata.parameters:
            if param.required and param.name not in parameters:
                raise ToolValidationError(f"Required parameter '{param.name}' is missing")
            
            if param.name in parameters:
                value = parameters[param.name]
                
                # Type validation
                if not self._validate_type(value, param.type):
                    raise ToolValidationError(
                        f"Parameter '{param.name}' must be of type {param.type.__name__}, got {type(value).__name__}"
                    )
                
                # Custom validation rules
                if param.validation_rules:
                    self._apply_validation_rules(param.name, value, param.validation_rules)
                
                validated[param.name] = value
            elif param.default is not None:
                validated[param.name] = param.default
        
        return validated
    
    def validate_output(self, result: Any) -> Any:
        """
        Validate output result.
        
        Args:
            result: Output result to validate
            
        Returns:
            Validated result
        """
        # Basic type validation
        if not self._validate_type(result, self.metadata.return_type):
            logger.warning(
                f"Tool {self.metadata.name} returned {type(result).__name__}, expected {self.metadata.return_type.__name__}"
            )
        
        return result
    
    def _validate_type(self, value: Any, expected_type: Type) -> bool:
        """Validate value type."""
        if expected_type == Any:
            return True
        
        # Handle Union types (e.g., Optional[str])
        if hasattr(expected_type, '__origin__'):
            if expected_type.__origin__ is Union:
                return any(isinstance(value, arg) for arg in expected_type.__args__)
        
        return isinstance(value, expected_type)
    
    def _apply_validation_rules(self, param_name: str, value: Any, rules: Dict[str, Any]):
        """Apply custom validation rules."""
        if 'min_length' in rules and hasattr(value, '__len__'):
            if len(value) < rules['min_length']:
                raise ToolValidationError(f"Parameter '{param_name}' must have at least {rules['min_length']} characters")
        
        if 'max_length' in rules and hasattr(value, '__len__'):
            if len(value) > rules['max_length']:
                raise ToolValidationError(f"Parameter '{param_name}' must have at most {rules['max_length']} characters")
        
        if 'min_value' in rules and isinstance(value, (int, float)):
            if value < rules['min_value']:
                raise ToolValidationError(f"Parameter '{param_name}' must be at least {rules['min_value']}")
        
        if 'max_value' in rules and isinstance(value, (int, float)):
            if value > rules['max_value']:
                raise ToolValidationError(f"Parameter '{param_name}' must be at most {rules['max_value']}")
        
        if 'allowed_values' in rules:
            if value not in rules['allowed_values']:
                raise ToolValidationError(f"Parameter '{param_name}' must be one of {rules['allowed_values']}")
    
    def _check_rate_limit(self, user_id: Optional[str]) -> bool:
        """Check if rate limit is exceeded."""
        if not self.metadata.rate_limit:
            return True
        
        if not user_id:
            user_id = "anonymous"
        
        now = datetime.utcnow()
        minute_key = now.strftime("%Y-%m-%d-%H-%M")
        
        if user_id not in self._rate_limit_tracker:
            self._rate_limit_tracker[user_id] = {}
        
        user_tracker = self._rate_limit_tracker[user_id]
        
        # Clean old entries
        keys_to_remove = [k for k in user_tracker.keys() if k < minute_key]
        for key in keys_to_remove:
            del user_tracker[key]
        
        # Check current minute
        current_count = user_tracker.get(minute_key, 0)
        if current_count >= self.metadata.rate_limit:
            return False
        
        # Update counter
        user_tracker[minute_key] = current_count + 1
        return True
    
    def get_schema(self) -> Dict[str, Any]:
        """Get tool input schema for validation."""
        properties = {}
        required = []
        
        for param in self.metadata.parameters:
            prop_def = {
                "type": self._get_json_type(param.type),
                "description": param.description
            }
            
            if param.default is not None:
                prop_def["default"] = param.default
            
            if param.validation_rules:
                prop_def.update(param.validation_rules)
            
            properties[param.name] = prop_def
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False
        }
    
    def _get_json_type(self, python_type: Type) -> str:
        """Convert Python type to JSON schema type."""
        type_mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object"
        }
        
        return type_mapping.get(python_type, "string")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tool execution statistics."""
        return {
            "name": self.metadata.name,
            "execution_count": self._execution_count,
            "last_execution": self._last_execution.isoformat() if self._last_execution else None,
            "status": self.metadata.status.value,
            "category": self.metadata.category.value
        }


class ToolRegistry:
    """
    Tool registry for managing tool discovery, validation, and metadata.
    """
    
    def __init__(self):
        """Initialize tool registry."""
        self.tools: Dict[str, BaseTool] = {}
        self.tools_by_category: Dict[ToolCategory, List[str]] = {}
        self.tool_aliases: Dict[str, str] = {}
        
        # Registry settings
        self.auto_discovery = True
        self.strict_validation = True
        
        # Metrics
        self.metrics = {
            "tools_registered": 0,
            "tools_executed": 0,
            "execution_errors": 0,
            "last_registration": None
        }
    
    def register_tool(self, tool: BaseTool, aliases: Optional[List[str]] = None) -> bool:
        """
        Register a tool in the registry.
        
        Args:
            tool: Tool instance to register
            aliases: Optional list of aliases for the tool
            
        Returns:
            True if registration successful, False otherwise
        """
        try:
            # Validate tool
            if not isinstance(tool, BaseTool):
                raise ValueError("Tool must inherit from BaseTool")
            
            metadata = tool.metadata
            tool_name = metadata.name
            
            # Check for name conflicts
            if tool_name in self.tools:
                logger.warning(f"Tool {tool_name} already registered, overwriting")
            
            # Register tool
            self.tools[tool_name] = tool
            
            # Update category index
            category = metadata.category
            if category not in self.tools_by_category:
                self.tools_by_category[category] = []
            
            if tool_name not in self.tools_by_category[category]:
                self.tools_by_category[category].append(tool_name)
            
            # Register aliases
            if aliases:
                for alias in aliases:
                    self.tool_aliases[alias] = tool_name
            
            # Update metrics
            self.metrics["tools_registered"] += 1
            self.metrics["last_registration"] = datetime.utcnow()
            
            logger.info(f"Tool {tool_name} registered successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register tool: {e}")
            return False
    
    def unregister_tool(self, tool_name: str) -> bool:
        """
        Unregister a tool from the registry.
        
        Args:
            tool_name: Name of the tool to unregister
            
        Returns:
            True if unregistration successful, False otherwise
        """
        try:
            if tool_name not in self.tools:
                logger.warning(f"Tool {tool_name} not found in registry")
                return False
            
            tool = self.tools[tool_name]
            category = tool.metadata.category
            
            # Remove from main registry
            del self.tools[tool_name]
            
            # Remove from category index
            if category in self.tools_by_category:
                if tool_name in self.tools_by_category[category]:
                    self.tools_by_category[category].remove(tool_name)
                
                # Clean up empty categories
                if not self.tools_by_category[category]:
                    del self.tools_by_category[category]
            
            # Remove aliases
            aliases_to_remove = [alias for alias, name in self.tool_aliases.items() if name == tool_name]
            for alias in aliases_to_remove:
                del self.tool_aliases[alias]
            
            logger.info(f"Tool {tool_name} unregistered successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister tool {tool_name}: {e}")
            return False
    
    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        Get a tool by name or alias.
        
        Args:
            tool_name: Name or alias of the tool
            
        Returns:
            Tool instance if found, None otherwise
        """
        # Check direct name
        if tool_name in self.tools:
            return self.tools[tool_name]
        
        # Check aliases
        if tool_name in self.tool_aliases:
            actual_name = self.tool_aliases[tool_name]
            return self.tools.get(actual_name)
        
        return None
    
    def list_tools(self, category: Optional[ToolCategory] = None, status: Optional[ToolStatus] = None) -> List[str]:
        """
        List available tools.
        
        Args:
            category: Filter by category
            status: Filter by status
            
        Returns:
            List of tool names
        """
        tools = []
        
        if category:
            tools = self.tools_by_category.get(category, [])
        else:
            tools = list(self.tools.keys())
        
        if status:
            tools = [name for name in tools if self.tools[name].metadata.status == status]
        
        return sorted(tools)
    
    def get_tool_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """
        Get tool metadata.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool metadata if found, None otherwise
        """
        tool = self.get_tool(tool_name)
        return tool.metadata if tool else None
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get tool input schema.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool schema if found, None otherwise
        """
        tool = self.get_tool(tool_name)
        return tool.get_schema() if tool else None
    
    def search_tools(self, query: str) -> List[str]:
        """
        Search tools by name, description, or tags.
        
        Args:
            query: Search query
            
        Returns:
            List of matching tool names
        """
        query_lower = query.lower()
        matches = []
        
        for tool_name, tool in self.tools.items():
            metadata = tool.metadata
            
            # Check name
            if query_lower in tool_name.lower():
                matches.append(tool_name)
                continue
            
            # Check description
            if query_lower in metadata.description.lower():
                matches.append(tool_name)
                continue
            
            # Check tags
            if any(query_lower in tag.lower() for tag in metadata.tags):
                matches.append(tool_name)
                continue
        
        return sorted(matches)
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        stats = {
            "total_tools": len(self.tools),
            "by_category": {},
            "by_status": {},
            "metrics": self.metrics.copy()
        }
        
        # Count by category
        for category, tool_names in self.tools_by_category.items():
            stats["by_category"][category.value] = len(tool_names)
        
        # Count by status
        for tool in self.tools.values():
            status = tool.metadata.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        
        return stats


class ToolService:
    """
    Main tool service providing unified tool management and execution.
    """
    
    def __init__(self, registry: Optional[ToolRegistry] = None):
        """Initialize tool service."""
        self.registry = registry or ToolRegistry()
        self.execution_cache: Dict[str, ToolOutput] = {}
        self.cache_ttl = 300  # 5 minutes
        
        # Service settings
        self.enable_caching = True
        self.default_timeout = 30
        
        # Metrics
        self.metrics = {
            "executions_total": 0,
            "executions_cached": 0,
            "executions_successful": 0,
            "executions_failed": 0,
            "average_execution_time": 0.0
        }

        self._bootstrap_builtin_tools()

    def _bootstrap_builtin_tools(self) -> None:
        """Register built-in production tools so the registry is not empty on startup."""
        try:
            from ai_karen_engine.tools import get_production_tools

            for tool in get_production_tools():
                if self.registry.get_tool(tool.metadata.name) is None:
                    self.registry.register_tool(tool)
        except Exception as e:
            logger.warning(f"Failed to register production tools: {e}")

    async def execute_tool(self, tool_input: ToolInput) -> ToolOutput:
        """
        Execute a tool with caching and error handling.
        
        Args:
            tool_input: Tool input containing name, parameters, and context
            
        Returns:
            Tool output with result or error
        """
        try:
            # Check cache first
            if self.enable_caching:
                cached_result = self._get_cached_result(tool_input)
                if cached_result:
                    self.metrics["executions_cached"] += 1
                    return cached_result
            
            # Get tool
            tool = self.registry.get_tool(tool_input.tool_name)
            if not tool:
                return ToolOutput(
                    success=False,
                    result=None,
                    error=f"Tool '{tool_input.tool_name}' not found",
                    execution_time=0.0,
                    request_id=tool_input.request_id
                )
            
            # Check tool status
            if tool.metadata.status != ToolStatus.AVAILABLE:
                return ToolOutput(
                    success=False,
                    result=None,
                    error=f"Tool '{tool_input.tool_name}' is not available (status: {tool.metadata.status.value})",
                    execution_time=0.0,
                    request_id=tool_input.request_id
                )
            
            # Execute tool
            result = await tool.execute(tool_input)
            
            # Cache successful results
            if self.enable_caching and result.success:
                self._cache_result(tool_input, result)
            
            # Update metrics
            self.metrics["executions_total"] += 1
            if result.success:
                self.metrics["executions_successful"] += 1
            else:
                self.metrics["executions_failed"] += 1
            
            # Update average execution time
            total_time = (self.metrics["average_execution_time"] * (self.metrics["executions_total"] - 1) + 
                         result.execution_time)
            self.metrics["average_execution_time"] = total_time / self.metrics["executions_total"]
            
            return result
            
        except Exception as e:
            logger.error(f"Tool service execution error: {e}")
            self.metrics["executions_total"] += 1
            self.metrics["executions_failed"] += 1
            
            return ToolOutput(
                success=False,
                result=None,
                error=f"Tool service error: {str(e)}",
                execution_time=0.0,
                request_id=tool_input.request_id
            )
    
    def _get_cached_result(self, tool_input: ToolInput) -> Optional[ToolOutput]:
        """Get cached result if available and not expired."""
        cache_key = self._generate_cache_key(tool_input)
        
        if cache_key in self.execution_cache:
            cached_result = self.execution_cache[cache_key]
            
            # Check if cache is still valid
            age = (datetime.utcnow() - cached_result.timestamp).total_seconds()
            if age < self.cache_ttl:
                # Create new output with updated request_id
                return ToolOutput(
                    success=cached_result.success,
                    result=cached_result.result,
                    error=cached_result.error,
                    execution_time=0.0,  # Cached, so no execution time
                    request_id=tool_input.request_id,
                    metadata={**(cached_result.metadata or {}), "cached": True}
                )
            else:
                # Remove expired cache entry
                del self.execution_cache[cache_key]
        
        return None
    
    def _cache_result(self, tool_input: ToolInput, result: ToolOutput):
        """Cache execution result."""
        cache_key = self._generate_cache_key(tool_input)
        self.execution_cache[cache_key] = result
        
        # Clean up old cache entries periodically
        if len(self.execution_cache) > 1000:  # Arbitrary limit
            self._cleanup_cache()
    
    def _generate_cache_key(self, tool_input: ToolInput) -> str:
        """Generate cache key for tool input."""
        # Create deterministic key from tool name and parameters
        key_data = {
            "tool_name": tool_input.tool_name,
            "parameters": tool_input.parameters
        }
        return f"{tool_input.tool_name}:{hash(json.dumps(key_data, sort_keys=True))}"
    
    def _cleanup_cache(self):
        """Clean up expired cache entries."""
        now = datetime.utcnow()
        expired_keys = []
        
        for key, result in self.execution_cache.items():
            age = (now - result.timestamp).total_seconds()
            if age >= self.cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.execution_cache[key]
    
    def register_tool(self, tool: BaseTool, aliases: Optional[List[str]] = None) -> bool:
        """Register a tool."""
        return self.registry.register_tool(tool, aliases)
    
    def unregister_tool(self, tool_name: str) -> bool:
        """Unregister a tool."""
        return self.registry.unregister_tool(tool_name)
    
    def list_tools(self, category: Optional[ToolCategory] = None, status: Optional[ToolStatus] = None) -> List[str]:
        """List available tools."""
        return self.registry.list_tools(category, status)
    
    def get_tool_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """Get tool metadata."""
        return self.registry.get_tool_metadata(tool_name)
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get tool input schema."""
        return self.registry.get_tool_schema(tool_name)
    
    def search_tools(self, query: str) -> List[str]:
        """Search tools."""
        return self.registry.search_tools(query)
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Get comprehensive service statistics."""
        return {
            "service_metrics": self.metrics.copy(),
            "registry_stats": self.registry.get_registry_stats(),
            "cache_size": len(self.execution_cache),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def clear_cache(self):
        """Clear execution cache."""
        self.execution_cache.clear()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the tool service."""
        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        try:
            # Check registry
            registry_stats = self.registry.get_registry_stats()
            health["components"]["registry"] = {
                "status": "healthy",
                "total_tools": registry_stats["total_tools"]
            }
            
            # Check cache
            health["components"]["cache"] = {
                "status": "healthy",
                "size": len(self.execution_cache),
                "enabled": self.enable_caching
            }
            
            # Check metrics
            success_rate = 0
            if self.metrics["executions_total"] > 0:
                success_rate = self.metrics["executions_successful"] / self.metrics["executions_total"]
            
            health["components"]["execution"] = {
                "status": "healthy" if success_rate > 0.8 else "degraded",
                "success_rate": success_rate,
                "total_executions": self.metrics["executions_total"]
            }
            
        except Exception as e:
            health["status"] = "unhealthy"
            health["error"] = str(e)
            logger.error(f"Tool service health check failed: {e}")
        
        return health


# Global tool service instance
_tool_service: Optional[ToolService] = None


def get_tool_service() -> ToolService:
    """Get global tool service instance."""
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolService()
    return _tool_service


async def initialize_tool_service(registry: Optional[ToolRegistry] = None) -> ToolService:
    """
    Initialize the global tool service.
    
    Args:
        registry: Optional tool registry to use
        
    Returns:
        Initialized tool service
    """
    global _tool_service
    _tool_service = ToolService(registry)
    return _tool_service
