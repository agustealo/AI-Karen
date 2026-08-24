"""
Agent Orchestrator Service

.. deprecated::
    The legacy agent orchestrator is deprecated. Use ``ai_karen_engine.agent_medusa``
    and ``ai_karen_engine.core.runtime`` for canonical multi-agent execution.
"""

import asyncio
import logging
import uuid
import warnings
from typing import Any, Dict, List, Optional, Set, Tuple, Union

warnings.warn(
    "ai_karen_engine.agents.agent_orchestrator is deprecated. "
    "Use ai_karen_engine.agent_medusa and ai_karen_engine.core.runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)
from datetime import datetime, timedelta
from enum import Enum

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.database.client import MultiTenantPostgresClient

from .internal import agent_schemas
from .internal import agent_validation
from .internal import agent_metrics
from .agent_memory import MemoryAccessLevel, MemorySharingPolicy
from .agent_reasoning import ReasoningType, ReasoningStrategy, ReasoningConfidence
from .agent_tool_broker import ToolStatus, AccessDecision
logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Agent role enumeration."""

    COORDINATOR = "coordinator"
    WORKER = "worker"
    SPECIALIST = "specialist"
    MANAGER = "manager"
    DELEGATOR = "delegator"


class AgentPriority(str, Enum):
    """Agent priority enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentOrchestrator(BaseService):
    """
    Enhanced Agent Orchestrator service for managing AI agents and their tasks.

    This service coordinates between different AI agents, manages their lifecycle,
    routes tasks to appropriate agents, and integrates with memory and AI services.
    """

    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_orchestrator"))
        self._initialized = False

        # Core services
        self._validation_service: Optional[agent_validation.AgentValidation] = None
        self._metrics_service: Optional[agent_metrics.AgentMetrics] = None
        self._memory_service: Optional[Any] = None  # UnifiedMemoryService
        self._langgraph_orchestrator: Optional[Any] = None  # AIOrchestrator
        self._model_orchestrator: Optional[Any] = None  # ModelOrchestratorService
        self._default_model: str = "gpt-3.5-turbo"  # Default model for agent operations
        self._model_preferences: Dict[str, str] = {}  # agent_id -> model_id mapping
        self._agent_registry: Optional[Any] = None  # AgentRegistry
        self._agent_memory: Optional[Any] = None  # AgentMemory
        self._agent_memory_fusion: Optional[Any] = None  # AgentMemoryFusion

        # Service discovery
        self._service_registry: Dict[str, Any] = {}
        self._service_discovery_enabled = True

        # Agent management
        self._agents: Dict[str, agent_schemas.AgentDefinition] = {}
        self._agent_instances: Dict[str, Any] = {}  # Running agent instances
        self._agent_sessions: Dict[str, agent_schemas.AgentSession] = {}
        self._agent_teams: Dict[str, Dict[str, Any]] = {}  # team_id -> team_info

        # Task management
        self._task_queue: List[agent_schemas.AgentTask] = []
        self._task_history: Dict[str, agent_schemas.AgentTask] = {}  # task_id -> task
        self._active_tasks: Dict[str, str] = {}  # task_id -> agent_id

        # Communication
        self._message_queue: List[agent_schemas.AgentMessage] = []
        self._message_history: Dict[
            str, agent_schemas.AgentMessage
        ] = {}  # message_id -> message

        # Configuration
        self._max_concurrent_tasks = 10
        self._task_timeout_seconds = 300  # 5 minutes
        self._session_timeout_hours = 24
        self._memory_sharing_enabled = True
        self._auto_scaling_enabled = True

        # Karen's system integration attributes
        self._karen_integration_enabled = False
        self._karen_flows = {}  # Dictionary for flow mappings
        self._karen_flow_results = {}  # Dictionary for flow results
        self._agent_karen_mappings = {}  # Dictionary to map agent types to flow types
        self._karen_flow_timeout = 60  # Default timeout for Karen flows (seconds)
        self._karen_max_retries = 3  # Default max retries for Karen flows
        self._karen_processor_running: bool = False
        self._karen_integration_task: Optional[asyncio.Task] = None

        # Karen's system integration metrics
        self._karen_flows_executed = 0
        self._karen_flows_completed = 0
        self._karen_flows_failed = 0
        self._karen_flow_times = []  # List to track flow execution times for calculating average

        # Locks for thread safety
        self._agents_lock = asyncio.Lock()
        self._tasks_lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._messages_lock = asyncio.Lock()

    @staticmethod
    def _flow_result_data(result: Any) -> Dict[str, Any]:
        """Normalize flow results to a dictionary."""
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return {"result": result}

    async def _load_configuration(self) -> None:
        """Load configuration for Karen's system integration settings."""
        try:
            logger.info("Loading Karen's system integration configuration")

            # Load configuration for Karen integration
            karen_config = self.config.data.get("karen_integration", {})

            # Load karen_integration_enabled from config
            self._karen_integration_enabled = karen_config.get("enabled", False)

            # Load karen_flow_timeout from config
            self._karen_flow_timeout = karen_config.get("flow_timeout", 60)

            # Load karen_max_retries from config
            self._karen_max_retries = karen_config.get("max_retries", 3)

            # Load any other Karen's system integration settings from config
            self._karen_flows = karen_config.get("flow_mappings", {})
            self._agent_karen_mappings = karen_config.get("agent_mappings", {})

            logger.info(
                f"Loaded Karen integration configuration: enabled={self._karen_integration_enabled}, "
                f"flow_timeout={self._karen_flow_timeout}, max_retries={self._karen_max_retries}"
            )

        except Exception as e:
            logger.error(f"Error loading Karen's system integration configuration: {e}")
            # Use default values if configuration loading fails
            self._karen_integration_enabled = False
            self._karen_flow_timeout = 60
            self._karen_max_retries = 3
            self._karen_flows = {}
            self._agent_karen_mappings = {}

    async def initialize(self) -> None:
        """Initialize Agent Orchestrator service."""
        if self._initialized:
            return

        logger.info("Initializing Agent Orchestrator service")

        try:
            # Load configuration first
            await self._load_configuration()

            # Initialize internal services
            self._validation_service = agent_validation.AgentValidation(
                config=ServiceConfig(name="agent_validation")
            )
            await self._validation_service.initialize()

            self._metrics_service = agent_metrics.AgentMetrics(
                config=ServiceConfig(name="agent_metrics")
            )
            await self._metrics_service.initialize()

            # Set up Karen integration
            await self._setup_karen_integration()

            # Initialize memory services if available
            await self._initialize_memory_services()

            # Initialize AI orchestrator if available
            await self._initialize_langgraph_orchestrator()

            # Initialize model orchestrator if available
            await self._initialize_model_orchestrator()

            # Initialize agent registry if available
            await self._initialize_agent_registry()

            # Start background tasks
            asyncio.create_task(self._task_processor())
            asyncio.create_task(self._message_processor())
            asyncio.create_task(self._session_monitor())
            asyncio.create_task(self._resource_monitor())
            asyncio.create_task(self._karen_integration_processor())

            self._initialized = True
            logger.info("Agent Orchestrator service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Agent Orchestrator: {e}")
            raise

    async def _setup_karen_integration(self) -> Dict[str, Any]:
        """
        Set up the integration with Karen's system.

        This method initializes the Karen flow mappings and agent-Karen mappings
        based on the configuration, and sets the Karen integration enabled flag.

        Returns:
            Dictionary with setup result information
        """
        try:
            logger.info("Setting up Karen integration")

            # Load configuration for Karen integration
            karen_config = self.config.data.get("karen_integration", {})
            self._karen_integration_enabled = karen_config.get("enabled", False)
            self._karen_flow_timeout = karen_config.get("flow_timeout", 60)
            self._karen_max_retries = karen_config.get("max_retries", 3)

            if self._karen_integration_enabled:
                logger.info("Karen integration enabled")

                # Initialize the _karen_flows dictionary with appropriate flow mappings
                self._karen_flows = karen_config.get("flow_mappings", {})
                logger.info(f"Initialized {len(self._karen_flows)} Karen flow mappings")

                # Initialize the _agent_karen_mappings dictionary with mappings from agent types to flow types
                self._agent_karen_mappings = karen_config.get("agent_mappings", {})
                logger.info(
                    f"Initialized {len(self._agent_karen_mappings)} agent-Karen mappings"
                )

                return {
                    "success": True,
                    "enabled": True,
                    "flow_mappings_count": len(self._karen_flows),
                    "agent_mappings_count": len(self._agent_karen_mappings),
                    "message": "Karen integration set up successfully",
                }
            else:
                logger.info("Karen integration disabled")
                return {
                    "success": True,
                    "enabled": False,
                    "message": "Karen integration is disabled in configuration",
                }

        except Exception as e:
            logger.error(f"Error setting up Karen integration: {e}")
            return {
                "success": False,
                "enabled": False,
                "error": str(e),
                "message": "Failed to set up Karen integration",
            }

    async def _handle_service_error(
        self, service_name: str, error: Exception, operation: str
    ) -> None:
        """
        Handle errors from integrated services with recovery mechanisms.

        Args:
            service_name: Name of the service that failed
            error: The exception that occurred
            operation: Operation that was being performed
        """
        error_id = str(uuid.uuid4())
        logger.error(
            f"Error in {service_name} during {operation} (ID: {error_id}): {error}"
        )

        # Record error metrics
        if self._metrics_service:
            try:
                await self._metrics_service.record_error(
                    "agent_orchestrator", f"{service_name}_{operation}"
                )
            except Exception as metrics_error:
                logger.error(f"Failed to record error metrics: {metrics_error}")

        # Set service to degraded state temporarily
        degraded_services = getattr(self, "_degraded_services", {})
        degraded_services[service_name] = {
            "error_id": error_id,
            "error": str(error),
            "operation": operation,
            "timestamp": datetime.utcnow(),
            "recovery_attempts": 0,
        }
        self._degraded_services = degraded_services

        # Attempt to recover based on service type
        recovery_success = False
        if service_name == "langgraph_orchestrator":
            # Try to reinitialize the LangGraph orchestrator
            try:
                logger.info(
                    f"Attempting to recover LangGraph orchestrator after error in {operation} (ID: {error_id})"
                )
                await self._initialize_langgraph_orchestrator()
                recovery_success = True
                logger.info(
                    f"Successfully recovered LangGraph orchestrator after error in {operation}"
                )
            except Exception as recovery_error:
                logger.error(
                    f"Failed to recover LangGraph orchestrator (ID: {error_id}): {recovery_error}"
                )
                # Increment recovery attempts
                if service_name in self._degraded_services:
                    self._degraded_services[service_name]["recovery_attempts"] += 1

        elif service_name == "model_orchestrator":
            # Try to reinitialize model orchestrator
            try:
                logger.info(
                    f"Attempting to recover model orchestrator after error in {operation} (ID: {error_id})"
                )
                await self._initialize_model_orchestrator()
                recovery_success = True
                logger.info(
                    f"Successfully recovered model orchestrator after error in {operation}"
                )
            except Exception as recovery_error:
                logger.error(
                    f"Failed to recover model orchestrator (ID: {error_id}): {recovery_error}"
                )
                # Increment recovery attempts
                if service_name in self._degraded_services:
                    self._degraded_services[service_name]["recovery_attempts"] += 1

        elif service_name == "memory_service":
            # Try to reinitialize memory service
            try:
                logger.info(
                    f"Attempting to recover memory service after error in {operation} (ID: {error_id})"
                )
                await self._initialize_memory_services()
                recovery_success = True
                logger.info(
                    f"Successfully recovered memory service after error in {operation}"
                )
            except Exception as recovery_error:
                logger.error(
                    f"Failed to recover memory service (ID: {error_id}): {recovery_error}"
                )
                # Increment recovery attempts
                if service_name in self._degraded_services:
                    self._degraded_services[service_name]["recovery_attempts"] += 1

        elif service_name == "agent_registry":
            # Try to reinitialize agent registry
            try:
                logger.info(
                    f"Attempting to recover agent registry after error in {operation} (ID: {error_id})"
                )
                await self._initialize_agent_registry()
                recovery_success = True
                logger.info(
                    f"Successfully recovered agent registry after error in {operation}"
                )
            except Exception as recovery_error:
                logger.error(
                    f"Failed to recover agent registry (ID: {error_id}): {recovery_error}"
                )
                # Increment recovery attempts
                if service_name in self._degraded_services:
                    self._degraded_services[service_name]["recovery_attempts"] += 1

        # If recovery was successful, remove from degraded services
        if recovery_success and service_name in self._degraded_services:
            del self._degraded_services[service_name]
            logger.info(f"Service {service_name} removed from degraded state")

        # If recovery failed multiple times, implement circuit breaker pattern
        elif (
            service_name in self._degraded_services
            and self._degraded_services[service_name]["recovery_attempts"] >= 3
        ):
            logger.warning(
                f"Service {service_name} has failed recovery 3 times, entering circuit breaker mode"
            )
            # Implement circuit breaker logic here - could disable service for a period
            # This is a placeholder for circuit breaker implementation

    async def _discover_service(self, service_name: str) -> Optional[Any]:
        """
        Discover and initialize a service using service discovery pattern.

        Args:
            service_name: Name of the service to discover

        Returns:
            The discovered service instance or None if not found
        """
        if not self._service_discovery_enabled:
            return None

        # Check if service is already discovered and available
        if service_name in self._service_registry:
            service = self._service_registry[service_name]
            # Perform basic health check
            try:
                if hasattr(service, "health_check"):
                    if await service.health_check():
                        return service
                    else:
                        # Service exists but is unhealthy, remove from registry
                        del self._service_registry[service_name]
                        logger.warning(
                            f"Service {service_name} was unhealthy, removed from registry"
                        )
                        return None
                else:
                    # No health check method available, assume healthy
                    return service
            except Exception as e:
                logger.error(f"Error checking health of service {service_name}: {e}")
                # Remove from registry
                if service_name in self._service_registry:
                    del self._service_registry[service_name]
                return None

        # Service not in registry, try to discover it
        service = None

        try:
            if service_name == "langgraph_orchestrator":
                try:
                    from ai_karen_engine.core.langgraph_orchestrator import (
                        LangGraphOrchestrator,
                    )

                    service = LangGraphOrchestrator()
                    await service.initialize()
                except ImportError:
                    logger.warning(
                        "LangGraph Orchestrator service not available for discovery"
                    )
                    return None

            elif service_name == "model_orchestrator":
                try:
                    from ai_karen_engine.services.model_orchestrator_service import (
                        ModelOrchestratorService,
                    )

                    service = ModelOrchestratorService()
                    service.initialize({})
                except ImportError:
                    logger.warning(
                        "Model Orchestrator service not available for discovery"
                    )
                    return None

            elif service_name == "agent_registry":
                try:
                    from .agent_registry import AgentRegistry

                    service = AgentRegistry(config=ServiceConfig(name="agent_registry"))
                    await service.initialize()
                except ImportError:
                    logger.warning("Agent Registry service not available for discovery")
                    return None

            elif service_name == "memory_service":
                try:
                    from ai_karen_engine.core.memory.unified_memory_service import (
                        UnifiedMemoryService,
                    )
                    from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
                    from ai_karen_engine.database.client import (
                        MultiTenantPostgresClient,
                    )

                    # These would normally be injected via dependency injection
                    # For now, we'll create placeholder instances
                    db_client = None  # Would be injected
                    embedding_manager = None  # Would be injected

                    if all([db_client, embedding_manager]):
                        service = UnifiedMemoryService(
                            db_client=db_client,
                            embedding_manager=embedding_manager,
                        )
                        logger.info("UnifiedMemoryService discovered and initialized")
                    else:
                        logger.warning(
                            "UnifiedMemoryService dependencies not available"
                        )
                        return None
                except ImportError:
                    logger.warning("Memory service not available for discovery")
                    return None

            elif service_name == "agent_memory":
                try:
                    from .agent_memory import EnhancedAgentMemory

                    service = EnhancedAgentMemory()
                    await service.initialize()
                except ImportError:
                    logger.warning("Agent Memory service not available for discovery")
                    return None

            elif service_name == "agent_memory_fusion":
                try:
                    from .agent_memory_fusion import AgentMemoryFusion

                    service = AgentMemoryFusion()
                    await service.initialize()
                except ImportError:
                    logger.warning(
                        "Agent Memory Fusion service not available for discovery"
                    )
                    return None

            # If service was successfully discovered and initialized, add to registry
            if service:
                self._service_registry[service_name] = service
                logger.info(f"Service {service_name} discovered and added to registry")
                return service

        except Exception as e:
            logger.error(f"Error discovering service {service_name}: {e}")
            return None

    async def _get_service(self, service_name: str) -> Optional[Any]:
        """
        Get a service instance, discovering it if necessary.

        Args:
            service_name: Name of the service to get

        Returns:
            The service instance or None if not available
        """
        # First try to get from service registry
        if service_name in self._service_registry:
            return self._service_registry[service_name]

        # If not in registry, try to discover it
        service = await self._discover_service(service_name)
        return service

    async def _release_service(self, service_name: str) -> bool:
        """
        Release a service instance from the registry.

        Args:
            service_name: Name of the service to release

        Returns:
            True if service was released, False if it wasn't registered
        """
        if service_name in self._service_registry:
            service = self._service_registry[service_name]

            # Try to properly shut down the service
            try:
                if hasattr(service, "shutdown"):
                    await service.shutdown()
                elif hasattr(service, "stop"):
                    await service.stop()
                elif hasattr(service, "close"):
                    await service.close()
            except Exception as e:
                logger.error(f"Error shutting down service {service_name}: {e}")

            # Remove from registry
            del self._service_registry[service_name]
            logger.info(f"Released service {service_name}")
            return True

        return False

    async def _check_service_health(self) -> Dict[str, Any]:
        """
        Check the health of all integrated services.

        Returns:
            Dictionary containing health status of all services
        """
        health_status = {
            "agent_orchestrator": {
                "status": "healthy",
                "initialized": self._initialized,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Check LangGraph orchestrator health
        if self._langgraph_orchestrator:
            try:
                ai_health = await self._langgraph_orchestrator.health_check()
                health_status["langgraph_orchestrator"] = {
                    "status": "healthy" if ai_health else "unhealthy",
                    "initialized": True,
                }
            except Exception as e:
                logger.error(f"Error checking LangGraph orchestrator health: {e}")
                health_status["langgraph_orchestrator"] = {
                    "status": "error",
                    "error": str(e),
                    "initialized": True,
                }
        else:
            health_status["langgraph_orchestrator"] = {
                "status": "not_available",
                "initialized": False,
            }

        # Check model orchestrator health
        if self._model_orchestrator:
            try:
                model_status = self._model_orchestrator.get_status()
                health_status["model_orchestrator"] = {
                    "status": "healthy"
                    if model_status.get("initialized", False)
                    else "unhealthy",
                    "initialized": model_status.get("initialized", False),
                    "providers": model_status.get("providers", {}),
                }
            except Exception as e:
                logger.error(f"Error checking model orchestrator health: {e}")
                health_status["model_orchestrator"] = {
                    "status": "error",
                    "error": str(e),
                    "initialized": True,
                }
        else:
            health_status["model_orchestrator"] = {
                "status": "not_available",
                "initialized": False,
            }

        # Check memory service health
        if self._memory_service:
            try:
                # Memory service doesn't have a health check method, so we'll check if it's initialized
                health_status["memory_service"] = {
                    "status": "healthy",
                    "initialized": True,
                }
            except Exception as e:
                logger.error(f"Error checking memory service health: {e}")
                health_status["memory_service"] = {
                    "status": "error",
                    "error": str(e),
                    "initialized": True,
                }
        else:
            health_status["memory_service"] = {
                "status": "not_available",
                "initialized": False,
            }

        # Check agent registry health
        if self._agent_registry:
            try:
                registry_health = await self._agent_registry.health_check()
                health_status["agent_registry"] = {
                    "status": "healthy" if registry_health else "unhealthy",
                    "initialized": True,
                }
            except Exception as e:
                logger.error(f"Error checking agent registry health: {e}")
                health_status["agent_registry"] = {
                    "status": "error",
                    "error": str(e),
                    "initialized": True,
                }
        else:
            health_status["agent_registry"] = {
                "status": "not_available",
                "initialized": False,
            }

        # Check Karen integration task health
        if self._karen_integration_enabled:
            try:
                # Check if Karen integration task is running and healthy
                karen_task_healthy = False
                if self._karen_integration_task:
                    karen_task_healthy = (
                        not self._karen_integration_task.done()
                        and not self._karen_integration_task.cancelled()
                    )

                health_status["karen_integration_task"] = {
                    "status": "healthy" if karen_task_healthy else "unhealthy",
                    "running": karen_task_healthy,
                    "processor_running": self._karen_processor_running,
                }
            except Exception as e:
                logger.error(f"Error checking Karen integration task health: {e}")
                health_status["karen_integration_task"] = {
                    "status": "error",
                    "error": str(e),
                    "running": False,
                    "processor_running": self._karen_processor_running,
                }
        else:
            health_status["karen_integration_task"] = {
                "status": "not_available",
                "running": False,
                "processor_running": False,
            }

        return health_status

    async def _initialize_memory_services(self) -> None:
        """Initialize memory services if available."""
        try:
            # Use service discovery to get memory services
            self._memory_service = await self._get_service("memory_service")
            if self._memory_service:
                logger.info("UnifiedMemoryService initialized via service discovery")
            else:
                logger.warning(
                    "UnifiedMemoryService not available via service discovery"
                )

            # Use service discovery to get agent memory services
            self._agent_memory = await self._get_service("agent_memory")
            self._agent_memory_fusion = await self._get_service("agent_memory_fusion")

            if self._agent_memory and self._agent_memory_fusion:
                logger.info("Agent memory services initialized via service discovery")
            else:
                logger.warning(
                    "Agent memory services not available via service discovery"
                )

        except Exception as e:
            logger.error(f"Failed to initialize memory services: {e}")

    async def _initialize_langgraph_orchestrator(self) -> None:
        """Initialize LangGraph orchestrator if available."""
        try:
            # Use service discovery to get LangGraph orchestrator
            self._langgraph_orchestrator = await self._get_service("langgraph_orchestrator")
            if self._langgraph_orchestrator:
                logger.info("LangGraph Orchestrator initialized via service discovery")
            else:
                logger.warning("LangGraph Orchestrator not available via service discovery")
        except Exception as e:
            logger.error(f"Failed to initialize LangGraph Orchestrator: {e}")

    async def _initialize_model_orchestrator(self) -> None:
        """Initialize model orchestrator if available."""
        try:
            # Use service discovery to get model orchestrator
            self._model_orchestrator = await self._get_service("model_orchestrator")
            if self._model_orchestrator:
                # Load model preferences from configuration if available
                model_config = self.config.data.get("models", {})
                self._default_model = model_config.get("default_model", "gpt-3.5-turbo")
                self._model_preferences = model_config.get("agent_preferences", {})

                logger.info(
                    "Model Orchestrator Service initialized via service discovery"
                )
            else:
                logger.warning(
                    "Model Orchestrator Service not available via service discovery"
                )
        except Exception as e:
            logger.error(f"Failed to initialize Model Orchestrator Service: {e}")

    async def _initialize_agent_registry(self) -> None:
        """Initialize agent registry if available."""
        try:
            # Use service discovery to get agent registry
            self._agent_registry = await self._get_service("agent_registry")
            if self._agent_registry:
                logger.info("Agent Registry initialized via service discovery")
            else:
                logger.warning("Agent Registry not available via service discovery")

        except Exception as e:
            logger.error(f"Failed to initialize Agent Registry: {e}")

    async def register_agent(
        self, agent_id: str, agent_type: str, config: Dict[str, Any]
    ) -> bool:
        """
        Register a new agent with orchestrator.

        Args:
            agent_id: Unique identifier for agent
            agent_type: Type/class of agent
            config: Configuration for agent

        Returns:
            True if registration was successful
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent configuration
        if self._validation_service:
            (
                is_valid,
                errors,
            ) = await self._validation_service.validate_agent_configuration(config)
            if not is_valid:
                logger.error(f"Agent configuration validation failed: {errors}")
                return False

        async with self._agents_lock:
            if agent_id in self._agents:
                logger.warning(f"Agent {agent_id} already registered")
                return False

            # Create agent definition
            agent_def = agent_schemas.AgentDefinition(
                agent_id=agent_id,
                name=config.get("name", agent_id),
                description=config.get("description", ""),
                agent_type=agent_type,
                version=config.get("version", "1.0.0"),
                config=config,
                status=agent_schemas.AgentStatus.READY,
            )

            self._agents[agent_id] = agent_def

            # Initialize agent instance
            await self._initialize_agent_instance(agent_id, agent_def)

            # Set up agent model preference if specified
            if "preferred_model" in config:
                await self.set_agent_model(agent_id, config["preferred_model"])

            # Set up Karen's system integration for the agent if enabled
            if self._karen_integration_enabled:
                try:
                    # Check if agent type has a mapping to a Karen flow type
                    if agent_type in self._agent_karen_mappings:
                        flow_type = self._agent_karen_mappings[agent_type]

                        # Set up Karen's system integration components for the agent
                        logger.info(
                            f"Setting up Karen's system integration for agent {agent_id} of type {agent_type} with flow type {flow_type}"
                        )

                        # Create Karen integration configuration for the agent
                        karen_config = {
                            "agent_id": agent_id,
                            "agent_type": agent_type,
                            "flow_type": flow_type,
                            "enabled": True,
                            "created_at": datetime.utcnow().isoformat(),
                        }

                        # Store Karen integration configuration in agent's config
                        if "karen_integration" not in agent_def.config:
                            agent_def.config["karen_integration"] = {}

                        agent_def.config["karen_integration"] = karen_config

                        # Execute any necessary setup flows for the agent
                        if flow_type in self._karen_flows:
                            flow_config = self._karen_flows[flow_type]
                            await self.execute_karen_flow(
                                flow_name=flow_type,
                                flow_data={
                                    "agent_id": agent_id,
                                    "agent_type": agent_type,
                                    "config": config,
                                    "operation": "setup",
                                },
                                agent_id=agent_id,
                            )

                            logger.info(
                                f"Executed Karen setup flow {flow_type} for agent {agent_id}"
                            )
                        else:
                            logger.warning(
                                f"No flow configuration found for flow type {flow_type} for agent {agent_id}"
                            )
                    else:
                        logger.info(
                            f"No Karen mapping found for agent type {agent_type}, skipping Karen integration setup"
                        )

                except Exception as e:
                    logger.error(
                        f"Error setting up Karen's system integration for agent {agent_id}: {e}"
                    )
                    # Continue with agent registration even if Karen integration setup fails

            # Register with agent registry if available
            if self._agent_registry:
                try:
                    registry_result = await self._agent_registry.register_agent(
                        agent_id=agent_id,
                        agent_type=agent_type,
                        config=config,
                        metadata={
                            "orchestrator": "agent_orchestrator",
                            "registered_at": datetime.utcnow().isoformat(),
                        },
                    )

                    if not registry_result.get("success", False):
                        logger.warning(
                            f"Failed to register agent {agent_id} with agent registry: {registry_result.get('error', 'Unknown error')}"
                        )
                    else:
                        logger.info(f"Registered agent {agent_id} with agent registry")

                except Exception as e:
                    logger.error(
                        f"Error registering agent {agent_id} with agent registry: {e}"
                    )

            logger.info(f"Registered agent {agent_id} of type {agent_type}")

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_agent_execution_time(agent_id, 0.0)
                await self._metrics_service.record_agent_success(agent_id)
                await self._metrics_service.record_session_start(agent_id)

            return True

    async def _initialize_agent_instance(
        self, agent_id: str, agent_def: agent_schemas.AgentDefinition
    ) -> None:
        """Initialize an agent instance."""
        try:
            # This would normally create an actual agent instance based on the type
            # For now, we'll create a placeholder
            agent_instance = {
                "agent_id": agent_id,
                "type": agent_def.agent_type,
                "status": agent_schemas.AgentStatus.READY,
                "capabilities": agent_def.config.get("capabilities", []),
                "resources": {"cpu": 0.0, "memory": 0.0, "active_tasks": 0},
            }

            self._agent_instances[agent_id] = agent_instance

            # Create agent session
            session_id = str(uuid.uuid4())
            session = agent_schemas.AgentSession(
                session_id=session_id,
                agent_id=agent_id,
                context=agent_def.config.copy(),
                status="active",
            )

            async with self._sessions_lock:
                self._agent_sessions[agent_id] = session

            logger.info(f"Initialized agent instance for {agent_id}")

        except Exception as e:
            logger.error(f"Failed to initialize agent instance for {agent_id}: {e}")
            raise

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Unregister an agent from orchestrator.

        Args:
            agent_id: Unique identifier for agent

        Returns:
            True if unregistration was successful
        """
        if not self._initialized:
            await self.initialize()

        async with self._agents_lock:
            if agent_id not in self._agents:
                logger.warning(f"Agent {agent_id} not registered")
                return False

            # Get agent definition before removal
            agent_def = self._agents[agent_id]

            # Terminate agent instance
            await self._terminate_agent_instance(agent_id)

            # Unregister from agent registry if available
            if self._agent_registry:
                try:
                    registry_result = await self._agent_registry.unregister_agent(
                        agent_id
                    )

                    if not registry_result.get("success", False):
                        logger.warning(
                            f"Failed to unregister agent {agent_id} from agent registry: {registry_result.get('error', 'Unknown error')}"
                        )
                    else:
                        logger.info(
                            f"Unregistered agent {agent_id} from agent registry"
                        )

                except Exception as e:
                    logger.error(
                        f"Error unregistering agent {agent_id} from agent registry: {e}"
                    )

            # Remove agent model preference
            if agent_id in self._model_preferences:
                del self._model_preferences[agent_id]

            # Remove agent
            del self._agents[agent_id]

            logger.info(f"Unregistered agent {agent_id}")

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_agent_failure(agent_id)

            return True

    async def _terminate_agent_instance(self, agent_id: str) -> None:
        """Terminate an agent instance."""
        try:
            # Cancel any active tasks
            async with self._tasks_lock:
                tasks_to_cancel = [
                    task_id
                    for task_id, assigned_agent in self._active_tasks.items()
                    if assigned_agent == agent_id
                ]

                for task_id in tasks_to_cancel:
                    await self._cancel_task(task_id)

            # Remove agent instance
            if agent_id in self._agent_instances:
                del self._agent_instances[agent_id]

            # Remove agent session
            async with self._sessions_lock:
                if agent_id in self._agent_sessions:
                    del self._agent_sessions[agent_id]

            logger.info(f"Terminated agent instance for {agent_id}")

        except Exception as e:
            logger.error(f"Failed to terminate agent instance for {agent_id}: {e}")

    async def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of an agent.

        Args:
            agent_id: Unique identifier for agent

        Returns:
            Agent status information or None if agent doesn't exist
        """
        if not self._initialized:
            await self.initialize()

        async with self._agents_lock:
            if agent_id not in self._agents:
                return None

            agent_def = self._agents[agent_id]
            agent_instance = self._agent_instances.get(agent_id, {})

            session_data = None
            if agent_id in self._agent_sessions:
                session_data = dict(self._agent_sessions[agent_id])

            return {
                "agent_id": agent_id,
                "definition": agent_def.dict(),
                "instance": agent_instance,
                "session": session_data,
            }

    async def list_agents(self) -> List[Dict[str, Any]]:
        """
        List all registered agents.

        Returns:
            List of agent information dictionaries
        """
        if not self._initialized:
            await self.initialize()

        async with self._agents_lock:
            return [
                {
                    "agent_id": agent_id,
                    "name": agent_def.name,
                    "type": agent_def.agent_type,
                    "status": agent_def.status,
                    "version": agent_def.version,
                    "capabilities": [cap.dict() for cap in agent_def.capabilities],
                    "registered_at": agent_def.created_at,
                    "instance": self._agent_instances.get(agent_id, {}),
                }
                for agent_id, agent_def in self._agents.items()
            ]

    async def create_task(
        self,
        task_type: str,
        task_data: Dict[str, Any],
        agent_id: Optional[str] = None,
        priority: int = 0,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a new task.

        Args:
            task_type: Type of task
            task_data: Data for task execution
            agent_id: Optional specific agent to assign task to
            priority: Task priority (higher = more important)
            timeout_seconds: Optional timeout in seconds

        Returns:
            Task creation result
        """
        if not self._initialized:
            await self.initialize()

        # Create task
        task_id = str(uuid.uuid4())
        task = agent_schemas.AgentTask(
            task_id=task_id,
            agent_id=agent_id or "",
            task_type=task_type,
            description=task_data.get("description", ""),
            input_data=task_data,
            priority=priority,
            timeout_seconds=timeout_seconds or self._task_timeout_seconds,
        )

        # Validate task
        if self._validation_service:
            is_valid, errors = await self._validation_service.validate_agent_task(task)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Task validation failed: {errors}",
                    "task_id": task_id,
                }

        # Add to queue
        async with self._tasks_lock:
            self._task_queue.append(task)
            self._task_history[task_id] = task

            # Sort queue by priority
            self._task_queue.sort(key=lambda t: t.priority, reverse=True)

        logger.info(f"Created task {task_id} of type {task_type}")

        # Record metrics
        if self._metrics_service:
            await self._metrics_service.record_task_queue_length(
                agent_id or "orchestrator", len(self._task_queue)
            )

        return {
            "success": True,
            "task_id": task_id,
            "status": task.status,
            "queue_position": len(self._task_queue),
        }

    async def _task_processor(self) -> None:
        """Background task to process the task queue."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue

                async with self._tasks_lock:
                    if not self._task_queue:
                        await asyncio.sleep(0.1)
                        continue

                    # Check if we can start a new task
                    active_count = len(self._active_tasks)
                    if active_count >= self._max_concurrent_tasks:
                        await asyncio.sleep(0.1)
                        continue

                    # Get next task
                    task = self._task_queue.pop(0)

                # Process task
                asyncio.create_task(self._execute_task(task))

                # Small delay to prevent CPU overload
                await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in task processor: {e}")
                await asyncio.sleep(1)

    async def _execute_task(self, task: agent_schemas.AgentTask) -> None:
        """Execute a task."""
        try:
            # Update task status
            task.status = agent_schemas.TaskStatus.RUNNING
            task.started_at = datetime.utcnow()

            # Record in active tasks
            async with self._tasks_lock:
                self._active_tasks[task.task_id] = task.agent_id

            # Select agent if not specified
            if not task.agent_id:
                selected_agent_id = await self._select_agent_for_task(task)
                if selected_agent_id:
                    # Update task with selected agent
                    task_dict = task.dict()
                    task_dict["agent_id"] = selected_agent_id
                    task = agent_schemas.AgentTask(**task_dict)

            if not task.agent_id:
                # No suitable agent found
                task.status = agent_schemas.TaskStatus.FAILED
                task.error = "No suitable agent found for task"
                task.completed_at = datetime.utcnow()

                # Update task history
                async with self._tasks_lock:
                    self._task_history[task.task_id] = task

                logger.warning(f"No agent found for task {task.task_id}")
                return

            # Get agent instance
            async with self._agents_lock:
                agent_instance = self._agent_instances.get(task.agent_id)

            if not agent_instance:
                # Agent not found
                task.status = agent_schemas.TaskStatus.FAILED
                task.error = f"Agent {task.agent_id} not found"
                task.completed_at = datetime.utcnow()

                # Update task history
                async with self._tasks_lock:
                    self._task_history[task.task_id] = task

                logger.error(f"Agent {task.agent_id} not found for task {task.task_id}")
                return

            # Update agent resource usage
            agent_instance["resources"]["active_tasks"] += 1

            try:
                # Execute task with timeout
                result = await asyncio.wait_for(
                    self._process_task_with_agent(task, agent_instance),
                    timeout=task.timeout_seconds,
                )

                # Update task status
                task.status = agent_schemas.TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.utcnow()

                logger.info(f"Task {task.task_id} completed successfully")

            except asyncio.TimeoutError:
                # Task timeout
                task.status = agent_schemas.TaskStatus.TIMEOUT
                task.error = "Task execution timeout"
                task.completed_at = datetime.utcnow()

                logger.warning(f"Task {task.task_id} timed out")

            except Exception as e:
                # Task execution error
                task.status = agent_schemas.TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.utcnow()

                logger.error(f"Task {task.task_id} failed: {e}")

            finally:
                # Update agent resource usage
                agent_instance["resources"]["active_tasks"] -= 1

                # Remove from active tasks
                async with self._tasks_lock:
                    if task.task_id in self._active_tasks:
                        del self._active_tasks[task.task_id]

                    # Update task history
                    self._task_history[task.task_id] = task

                # Record metrics
                if self._metrics_service:
                    if task.completed_at and task.started_at:
                        execution_time = (
                            task.completed_at - task.started_at
                        ).total_seconds()
                        await self._metrics_service.record_task_processing_time(
                            task.agent_id, execution_time
                        )

                    await self._metrics_service.record_task_status(
                        task.agent_id, task.status
                    )

                    if task.status == agent_schemas.TaskStatus.COMPLETED:
                        await self._metrics_service.record_agent_success(task.agent_id)
                    else:
                        await self._metrics_service.record_agent_failure(task.agent_id)

        except Exception as e:
            logger.error(f"Error executing task {task.task_id}: {e}")

    async def _select_agent_for_task(
        self, task: agent_schemas.AgentTask
    ) -> Optional[str]:
        """Select an appropriate agent for a task."""
        try:
            # Get all available agents
            async with self._agents_lock:
                available_agents = [
                    (agent_id, agent_def)
                    for agent_id, agent_def in self._agents.items()
                    if agent_def.status == agent_schemas.AgentStatus.READY
                ]

            if not available_agents:
                return None

            # Filter agents by capability
            capable_agents = []
            for agent_id, agent_def in available_agents:
                # Check if agent has required capabilities
                if self._agent_has_capability(agent_def, task.task_type):
                    capable_agents.append((agent_id, agent_def))

            if not capable_agents:
                return None

            # Select agent with lowest load
            best_agent_id = None
            lowest_load = float("inf")

            for agent_id, agent_def in capable_agents:
                agent_instance = self._agent_instances.get(agent_id, {})
                load = agent_instance.get("resources", {}).get("active_tasks", 0)

                if load < lowest_load:
                    lowest_load = load
                    best_agent_id = agent_id

            return best_agent_id

        except Exception as e:
            logger.error(f"Error selecting agent for task {task.task_id}: {e}")
            return None

    def _agent_has_capability(
        self, agent_def: agent_schemas.AgentDefinition, task_type: str
    ) -> bool:
        """Check if an agent has the capability for a task type."""
        # This is a simplified implementation
        # In a real system, this would check against agent capabilities
        return True

    async def _process_task_with_agent(
        self, task: agent_schemas.AgentTask, agent_instance: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process a task with an agent."""
        try:
            # This is where the actual task processing would happen
            # For now, we'll simulate task execution

            # Use AI orchestrator if available for reasoning
            if self._langgraph_orchestrator:
                # Determine the appropriate flow type based on task type
                flow_type = "decision"  # Default flow type
                if task.task_type in ["reasoning", "learning", "problem_solving"]:
                    flow_type = "analysis"
                elif task.task_type in ["conversation", "communication"]:
                    flow_type = "conversation"

                flow_input = {
                    "task_type": task.task_type,
                    "task_data": task.input_data,
                    "agent_id": task.agent_id,
                    "agent_capabilities": agent_instance.get("capabilities", []),
                    "context": {
                        "agent_status": agent_instance.get("status", "unknown"),
                        "agent_resources": agent_instance.get("resources", {}),
                    },
                }

                # Process the task using the appropriate flow
                flow_output = await self._langgraph_orchestrator.process_flow(
                    flow_type, flow_input
                )

                flow_output_data = self._flow_result_data(flow_output)

                if flow_output_data.get("result") == "error":
                    logger.error(
                        f"Flow processing failed for task {task.task_id}: {flow_output_data.get('message', 'Unknown error')}"
                    )
                    raise Exception(
                        flow_output_data.get("message", "Flow processing failed")
                    )

                result = flow_output_data

                # If the flow returned a decision, use it
                if flow_type == "decision" and "decision" in result:
                    result["action"] = result["decision"]

            else:
                # Fallback to simple processing
                result = {
                    "status": "completed",
                    "task_type": task.task_type,
                    "agent_id": task.agent_id,
                    "result": f"Processed task {task.task_id}",
                }

            return result

        except Exception as e:
            logger.error(
                f"Error processing task {task.task_id} with agent {task.agent_id}: {e}"
            )
            raise

    async def _cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        async with self._tasks_lock:
            if task_id not in self._task_history:
                return False

            task = self._task_history[task_id]

            if task.status in [
                agent_schemas.TaskStatus.COMPLETED,
                agent_schemas.TaskStatus.FAILED,
                agent_schemas.TaskStatus.CANCELLED,
            ]:
                return False

            # Update task status
            task.status = agent_schemas.TaskStatus.CANCELLED
            task.completed_at = datetime.utcnow()

            # Remove from active tasks
            if task_id in self._active_tasks:
                del self._active_tasks[task_id]

            logger.info(f"Cancelled task {task_id}")
            return True

    async def route_task(
        self, task_type: str, task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Route a task to appropriate agent.

        Args:
            task_type: Type of task to route
            task_data: Data for task execution

        Returns:
            Result of task routing/execution
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Routing task of type {task_type}")

        # Create task
        result = await self.create_task(task_type, task_data)

        if not result["success"]:
            return result

        # Wait for task completion (with timeout)
        task_id = result["task_id"]
        timeout = 30.0  # 30 seconds wait for completion

        try:
            # Wait for task to complete
            start_time = datetime.utcnow()
            while True:
                async with self._tasks_lock:
                    if task_id in self._task_history:
                        task = self._task_history[task_id]
                        if task.status in [
                            agent_schemas.TaskStatus.COMPLETED,
                            agent_schemas.TaskStatus.FAILED,
                            agent_schemas.TaskStatus.CANCELLED,
                            agent_schemas.TaskStatus.TIMEOUT,
                        ]:
                            return {
                                "status": task.status,
                                "task_id": task_id,
                                "task_type": task.task_type,
                                "agent_id": task.agent_id,
                                "result": task.result,
                                "error": task.error,
                            }

                # Check timeout
                if (datetime.utcnow() - start_time).total_seconds() > timeout:
                    return {
                        "status": "timeout",
                        "task_id": task_id,
                        "task_type": task_type,
                        "error": "Task routing timeout",
                    }

                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Error routing task {task_id}: {e}")
            return {
                "status": "error",
                "task_id": task_id,
                "task_type": task_type,
                "error": str(e),
            }

    async def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        message_type: str,
        content: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send a message between agents.

        Args:
            sender_id: ID of the sending agent
            recipient_id: ID of the receiving agent
            message_type: Type of message
            content: Message content

        Returns:
            Message sending result
        """
        if not self._initialized:
            await self.initialize()

        # Validate agents exist
        async with self._agents_lock:
            if sender_id not in self._agents:
                return {
                    "success": False,
                    "error": f"Sender agent {sender_id} not found",
                }

            if recipient_id not in self._agents:
                return {
                    "success": False,
                    "error": f"Recipient agent {recipient_id} not found",
                }

        # Create message
        message_id = str(uuid.uuid4())
        message = agent_schemas.AgentMessage(
            message_id=message_id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            message_type=message_type,
            content=content,
        )

        # Validate message
        if self._validation_service:
            is_valid, errors = await self._validation_service.validate_agent_message(
                message
            )
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Message validation failed: {errors}",
                }

        # Add to message queue
        async with self._messages_lock:
            self._message_queue.append(message)
            self._message_history[message_id] = message

        logger.info(f"Sent message {message_id} from {sender_id} to {recipient_id}")

        # Record metrics
        if self._metrics_service:
            await self._metrics_service.record_message(
                sender_id, recipient_id, message_type
            )

        return {"success": True, "message_id": message_id, "status": message.status}

    async def _message_processor(self) -> None:
        """Background task to process the message queue."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue

                async with self._messages_lock:
                    if not self._message_queue:
                        await asyncio.sleep(0.1)
                        continue

                    # Get next message
                    message = self._message_queue.pop(0)

                # Process message
                asyncio.create_task(self._deliver_message(message))

                # Small delay to prevent CPU overload
                await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in message processor: {e}")
                await asyncio.sleep(1)

    async def _deliver_message(self, message: agent_schemas.AgentMessage) -> None:
        """Deliver a message to the recipient agent."""
        try:
            # Update message status
            message.status = agent_schemas.MessageStatus.DELIVERED
            message.delivered_at = datetime.utcnow()

            # Get recipient agent
            async with self._agents_lock:
                agent_instance = self._agent_instances.get(message.recipient_id)

            if not agent_instance:
                # Agent not found
                message.status = agent_schemas.MessageStatus.FAILED
                logger.error(
                    f"Recipient agent {message.recipient_id} not found for message {message.message_id}"
                )
                return

            # Process message
            try:
                # This is where the actual message processing would happen
                # For now, we'll simulate message processing

                # Update message status
                message.status = agent_schemas.MessageStatus.PROCESSED
                message.processed_at = datetime.utcnow()

                logger.info(
                    f"Delivered message {message.message_id} to {message.recipient_id}"
                )

            except Exception as e:
                # Message processing error
                message.status = agent_schemas.MessageStatus.FAILED
                logger.error(f"Error processing message {message.message_id}: {e}")

            # Update message history
            async with self._messages_lock:
                self._message_history[message.message_id] = message

        except Exception as e:
            logger.error(f"Error delivering message {message.message_id}: {e}")

    async def _session_monitor(self) -> None:
        """Background task to monitor agent sessions."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue

                # Check for expired sessions
                now = datetime.utcnow()
                expired_sessions = []

                async with self._sessions_lock:
                    for agent_id, session in self._agent_sessions.items():
                        if session.expires_at and session.expires_at < now:
                            expired_sessions.append(agent_id)

                # Terminate expired sessions
                for agent_id in expired_sessions:
                    logger.info(f"Terminating expired session for agent {agent_id}")
                    await self._terminate_agent_instance(agent_id)

                # Sleep for a while
                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error in session monitor: {e}")
                await asyncio.sleep(60)

    async def _resource_monitor(self) -> None:
        """Background task to monitor resource usage."""
        while True:
            try:
                if not self._initialized:
                    await asyncio.sleep(1)
                    continue

                # Collect resource metrics
                async with self._agents_lock:
                    for agent_id, agent_instance in self._agent_instances.items():
                        resources = agent_instance.get("resources", {})

                        if self._metrics_service:
                            # Record CPU usage (simulated)
                            cpu_usage = resources.get("cpu", 0.0)
                            await self._metrics_service.record_cpu_usage(
                                agent_id, cpu_usage
                            )

                            # Record memory usage (simulated)
                            memory_usage = resources.get("memory", 0.0)
                            await self._metrics_service.record_memory_usage_bytes(
                                agent_id, memory_usage
                            )

                # Sleep for a while
                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Error in resource monitor: {e}")
                await asyncio.sleep(30)

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a task.

        Args:
            task_id: ID of the task

        Returns:
            Task status information or None if task doesn't exist
        """
        if not self._initialized:
            await self.initialize()

        async with self._tasks_lock:
            if task_id not in self._task_history:
                return None

            task = self._task_history[task_id]
            return task.dict()

    async def get_message_status(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a message.

        Args:
            message_id: ID of the message

        Returns:
            Message status information or None if message doesn't exist
        """
        if not self._initialized:
            await self.initialize()

        async with self._messages_lock:
            if message_id not in self._message_history:
                return None

            message = self._message_history[message_id]
            return message.dict()

    async def get_orchestrator_metrics(self) -> Dict[str, Any]:
        """
        Get orchestrator metrics.

        Returns:
            Orchestrator metrics
        """
        if not self._initialized:
            await self.initialize()

        # Calculate average Karen flow time
        avg_karen_flow_time = 0.0
        if self._karen_flow_times:
            avg_karen_flow_time = sum(self._karen_flow_times) / len(
                self._karen_flow_times
            )

        metrics = {
            "agents": {
                "total": len(self._agents),
                "ready": sum(
                    1
                    for agent in self._agents.values()
                    if agent.status == agent_schemas.AgentStatus.READY
                ),
                "busy": sum(
                    1
                    for agent in self._agents.values()
                    if agent.status == agent_schemas.AgentStatus.BUSY
                ),
            },
            "tasks": {
                "queued": len(self._task_queue),
                "active": len(self._active_tasks),
                "completed": sum(
                    1
                    for task in self._task_history.values()
                    if task.status == agent_schemas.TaskStatus.COMPLETED
                ),
                "failed": sum(
                    1
                    for task in self._task_history.values()
                    if task.status == agent_schemas.TaskStatus.FAILED
                ),
            },
            "messages": {
                "queued": len(self._message_queue),
                "delivered": sum(
                    1
                    for msg in self._message_history.values()
                    if msg.status == agent_schemas.MessageStatus.DELIVERED
                ),
                "processed": sum(
                    1
                    for msg in self._message_history.values()
                    if msg.status == agent_schemas.MessageStatus.PROCESSED
                ),
            },
            "sessions": {"active": len(self._agent_sessions)},
            "karen_integration": {
                "enabled": self._karen_integration_enabled,
                "flows_executed": self._karen_flows_executed,
                "flows_completed": self._karen_flows_completed,
                "flows_failed": self._karen_flows_failed,
                "avg_flow_time_seconds": avg_karen_flow_time,
                "flow_timeout_seconds": self._karen_flow_timeout,
                "max_retries": self._karen_max_retries,
            },
        }

        # Add detailed metrics if metrics service is available
        if self._metrics_service:
            metrics["detailed"] = await self._metrics_service.get_all_metrics()

        return metrics

    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of Agent Orchestrator service and all integrated services.

        Returns:
            A dictionary containing health status information
        """
        base_health = {
            "service": "agent_orchestrator",
            "timestamp": datetime.utcnow().isoformat(),
            "initialized": self._initialized,
            "agents_count": len(self._agents),
            "active_tasks": len(self._active_tasks),
            "queued_tasks": len(self._task_queue),
            "active_sessions": len(self._agent_sessions),
            "karen_integration": {
                "enabled": self._karen_integration_enabled,
                "flow_mappings_count": len(self._karen_flows),
                "agent_mappings_count": len(self._agent_karen_mappings),
                "flow_results_count": len(self._karen_flow_results),
                "flows_executed": self._karen_flows_executed,
                "flows_completed": self._karen_flows_completed,
                "flows_failed": self._karen_flows_failed,
                "status": "healthy",
            },
        }

        # Check health of Karen's system integration components
        if self._karen_integration_enabled:
            try:
                # Check if Karen integration processor is running
                # Since we don't have a direct way to check if the processor is running,
                # we'll use the initialization status as a proxy
                karen_processor_healthy = self._initialized

                # Check if we have flow mappings
                if len(self._karen_flows) > 0:
                    karen_flows_healthy = True
                else:
                    karen_flows_healthy = False

                # Update Karen integration status based on checks
                if karen_processor_healthy and karen_flows_healthy:
                    base_health["karen_integration"]["status"] = "healthy"
                elif karen_processor_healthy or karen_flows_healthy:
                    base_health["karen_integration"]["status"] = "degraded"
                else:
                    base_health["karen_integration"]["status"] = "unhealthy"

                # Calculate average flow time for health metrics
                avg_flow_time = 0.0
                if self._karen_flow_times:
                    avg_flow_time = sum(self._karen_flow_times) / len(
                        self._karen_flow_times
                    )

                base_health["karen_integration"]["avg_flow_time_seconds"] = (
                    avg_flow_time
                )
                base_health["karen_integration"]["processor_healthy"] = (
                    karen_processor_healthy
                )

            except Exception as e:
                logger.error(f"Error checking Karen integration health: {e}")
                base_health["karen_integration"]["status"] = "error"
                base_health["karen_integration"]["error"] = str(e)

        # Check health of dependent services
        if self._validation_service:
            base_health["validation_service"] = (
                "healthy"
                if await self._validation_service.health_check()
                else "unhealthy"
            )

        if self._metrics_service:
            base_health["metrics_service"] = (
                "healthy" if await self._metrics_service.health_check() else "unhealthy"
            )

        if self._agent_memory:
            base_health["agent_memory"] = (
                "healthy" if await self._agent_memory.health_check() else "unhealthy"
            )

        if self._agent_memory_fusion:
            base_health["agent_memory_fusion"] = (
                "healthy"
                if await self._agent_memory_fusion.health_check()
                else "unhealthy"
            )

        # Use comprehensive service health check
        try:
            service_health = await self._check_service_health()

            # Merge service health with base health
            health = {**base_health, **service_health}

            # Determine overall status
            unhealthy_services = [
                service
                for service, info in health.items()
                if service.endswith("_orchestrator")
                or service.endswith("_service")
                or service.endswith("_registry")
                if isinstance(info, dict)
                and info.get("status") not in ["healthy", "not_available"]
            ]

            # Check if Karen integration is unhealthy
            if self._karen_integration_enabled and base_health["karen_integration"].get(
                "status"
            ) not in ["healthy", "not_available"]:
                unhealthy_services.append("karen_integration")

            if unhealthy_services:
                health["status"] = "degraded"
                health["unhealthy_services"] = unhealthy_services
            else:
                health["status"] = "healthy"

            return health

        except Exception as e:
            logger.error(f"Error during comprehensive health check: {e}")
            # Fall back to basic health check
            base_health["status"] = "healthy"
            base_health["health_check_error"] = str(e)
            return base_health

    # Memory Integration Methods

    async def store_agent_memory(
        self,
        agent_id: str,
        memory_type: str,
        content: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        permission_level: agent_schemas.PermissionLevel = agent_schemas.PermissionLevel.READ,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Store agent memory using the memory service.

        Args:
            agent_id: ID of the agent
            memory_type: Type of memory
            content: Memory content
            metadata: Optional metadata
            permission_level: Access permission level
            tenant_id: Tenant ID for multi-tenancy

        Returns:
            Result of memory storage operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Create memory entry
            memory_id = str(uuid.uuid4())
            memory = agent_schemas.AgentMemory(
                memory_id=memory_id,
                agent_id=agent_id,
                memory_type=memory_type,
                content=content,
                metadata=metadata or {},
                permission_level=permission_level,
            )

            # Store in agent memory service
            if self._agent_memory:
                result = await self._agent_memory.store_memory(
                    agent_id=agent_id,
                    memory_type=memory_type,
                    content=content,
                    metadata=metadata,
                    permission_level=permission_level,
                )

                if not result.get("success", False):
                    logger.error(
                        f"Failed to store memory for agent {agent_id}: {result.get('error', 'Unknown error')}"
                    )
                    return result

            # Store in unified memory service if available
            if self._memory_service:
                try:
                    from ai_karen_engine.core.memory.unified_memory_service import (
                        MemoryCommitRequest,
                    )

                    # Convert content to text for unified memory service
                    content_text = str(content)

                    # Create MemoryCommitRequest with proper tenant isolation
                    memory_request = MemoryCommitRequest(
                        user_id=agent_id,  # Use agent_id as user_id for now
                        org_id=tenant_id,
                        text=content_text,
                        tags=[f"agent_{memory_type}"]
                        + (metadata.get("tags", []) if metadata else []),
                        importance=metadata.get("importance", 5) if metadata else 5,
                        decay=metadata.get("decay", "medium") if metadata else "medium",
                        metadata={
                            "agent_id": agent_id,
                            "memory_id": memory_id,
                            "memory_type": memory_type,
                            "original_content": content,
                            "permission_level": permission_level.value,
                            **(metadata or {}),
                        },
                    )

                    # Use tenant ID or default
                    tenant = tenant_id or agent_id

                    # Commit to unified memory service
                    memory_response = await self._memory_service.commit(
                        tenant_id=tenant, request=memory_request
                    )

                    if memory_response.success:
                        logger.info(
                            f"Stored memory {memory_id} for agent {agent_id} in unified memory"
                        )
                    else:
                        logger.error(
                            f"Failed to store memory in unified memory service: {memory_response.id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to store memory in unified memory service: {e}"
                    )

            logger.info(f"Stored memory {memory_id} for agent {agent_id}")

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_memory_operation(
                    agent_id, "store", memory_type
                )

            return {
                "success": True,
                "memory_id": memory_id,
                "agent_id": agent_id,
                "memory_type": memory_type,
            }

        except Exception as e:
            logger.error(f"Error storing memory for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def retrieve_agent_memory(
        self,
        agent_id: str,
        memory_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 10,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve agent memory from the memory service.

        Args:
            agent_id: ID of the agent
            memory_id: Optional specific memory ID to retrieve
            memory_type: Optional memory type to filter by
            limit: Maximum number of memories to retrieve
            tenant_id: Tenant ID for multi-tenancy

        Returns:
            Result of memory retrieval operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            memories = []

            # Try agent memory service first
            if self._agent_memory:
                if memory_id:
                    # Retrieve specific memory
                    result = await self._agent_memory.retrieve_memory(
                        agent_id, memory_id
                    )
                    if result.get("success", False):
                        memories = [result["memory"]]
                else:
                    # Retrieve memories by type
                    result = await self._agent_memory.get_memories_by_type(
                        agent_id=agent_id, memory_type=memory_type, limit=limit
                    )
                    if result.get("success", False):
                        memories = result.get("memories", [])

            # If no memories found, try unified memory service
            if not memories and self._memory_service:
                try:
                    from ai_karen_engine.core.memory.unified_memory_service import (
                        MemoryQueryRequest,
                    )

                    # Build query based on parameters
                    query_text = f"agent:{agent_id}"
                    if memory_id:
                        query_text += f" memory_id:{memory_id}"
                    if memory_type:
                        query_text += f" type:{memory_type}"

                    # Create MemoryQueryRequest with proper tenant isolation
                    memory_request = MemoryQueryRequest(
                        user_id=agent_id,  # Use agent_id as user_id for now
                        org_id=tenant_id,
                        query=query_text,
                        top_k=limit,
                        similarity_threshold=0.7,  # Default threshold
                        include_metadata=True,
                    )

                    # Use tenant ID or default
                    tenant = tenant_id or agent_id

                    # Query unified memory service
                    search_response = await self._memory_service.query(
                        tenant_id=tenant, request=memory_request
                    )

                    if search_response and search_response.hits:
                        # Convert to agent memory format
                        for hit in search_response.hits:
                            memories.append(
                                {
                                    "memory_id": hit.id,
                                    "agent_id": hit.user_id,
                                    "memory_type": hit.meta.get(
                                        "memory_type", "unknown"
                                    ),
                                    "content": hit.text,
                                    "metadata": hit.meta,
                                    "permission_level": hit.meta.get(
                                        "permission_level", "READ"
                                    ),
                                    "timestamp": hit.created_at.isoformat()
                                    if hit.created_at
                                    else None,
                                    "score": hit.score,
                                }
                            )

                    logger.info(
                        f"Retrieved {len(memories)} memories for agent {agent_id} from unified memory"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to retrieve memories from unified memory service: {e}"
                    )

            logger.info(f"Retrieved {len(memories)} memories for agent {agent_id}")

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_memory_operation(
                    agent_id, "retrieve", memory_type or "all"
                )

            return {
                "success": True,
                "agent_id": agent_id,
                "memories": memories,
                "count": len(memories),
            }

        except Exception as e:
            logger.error(f"Error retrieving memories for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def search_agent_memories(
        self,
        agent_id: str,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 10,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search agent memories using semantic search.

        Args:
            agent_id: ID of the agent
            query: Search query
            memory_type: Optional memory type to filter by
            limit: Maximum number of results
            tenant_id: Tenant ID for multi-tenancy

        Returns:
            Search results
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            results = []

            # Try agent memory service first
            if self._agent_memory:
                result = await self._agent_memory.search_memories(
                    agent_id=agent_id, query=query, memory_type=memory_type, limit=limit
                )

                if result.get("success", False):
                    results = result.get("results", [])

            # If no results, try unified memory service
            if self._memory_service:
                try:
                    from ai_karen_engine.core.memory.unified_memory_service import (
                        MemoryQueryRequest,
                    )

                    # Build search query with memory type filter
                    search_query = query
                    if memory_type:
                        search_query = f"{query} agent_{memory_type}"

                    # Create MemoryQueryRequest for semantic search
                    memory_request = MemoryQueryRequest(
                        user_id=agent_id,  # Use agent_id as user_id for now
                        org_id=tenant_id,
                        query=search_query,
                        top_k=limit,
                        similarity_threshold=0.5,  # Lower threshold for broader search
                        include_metadata=True,
                    )

                    # Use tenant ID or default
                    tenant = tenant_id or agent_id

                    # Perform semantic search using unified memory service
                    search_response = await self._memory_service.query(
                        tenant_id=tenant, request=memory_request
                    )

                    if search_response and search_response.hits:
                        # Convert to agent memory format
                        for hit in search_response.hits:
                            results.append(
                                {
                                    "memory_id": hit.id,
                                    "agent_id": hit.user_id,
                                    "memory_type": hit.meta.get(
                                        "memory_type", "unknown"
                                    ),
                                    "content": hit.text,
                                    "metadata": hit.meta,
                                    "permission_level": hit.meta.get(
                                        "permission_level", "READ"
                                    ),
                                    "timestamp": hit.created_at.isoformat()
                                    if hit.created_at
                                    else None,
                                    "score": hit.score,
                                }
                            )

                    logger.info(
                        f"Found {len(results)} memories for agent {agent_id} in unified memory"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to search memories in unified memory service: {e}"
                    )

            logger.info(f"Found {len(results)} memories for agent {agent_id}")

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_memory_operation(
                    agent_id, "search", memory_type or "all"
                )

            return {
                "success": True,
                "agent_id": agent_id,
                "query": query,
                "results": results,
                "count": len(results),
            }

        except Exception as e:
            logger.error(f"Error searching memories for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def share_agent_memory(
        self,
        agent_id: str,
        memory_id: str,
        target_agent_ids: List[str],
        permission_level: agent_schemas.PermissionLevel = agent_schemas.PermissionLevel.WRITE,
    ) -> Dict[str, Any]:
        """
        Share agent memory with other agents.

        Args:
            agent_id: ID of the source agent
            memory_id: ID of the memory to share
            target_agent_ids: List of target agent IDs
            permission_level: Permission level for shared memory

        Returns:
            Result of memory sharing operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate source agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Source agent {agent_id} not found"}

            # Validate target agents exist
            for target_id in target_agent_ids:
                if target_id not in self._agents:
                    return {
                        "success": False,
                        "error": f"Target agent {target_id} not found",
                    }

        try:
            # Retrieve the memory to share
            memory_result = await self.retrieve_agent_memory(
                agent_id, memory_id=memory_id
            )

            if not memory_result.get("success", False):
                return {
                    "success": False,
                    "error": f"Memory {memory_id} not found for agent {agent_id}",
                }

            memories = memory_result.get("memories", [])
            if not memories:
                return {
                    "success": False,
                    "error": f"Memory {memory_id} not found for agent {agent_id}",
                }

            memory_data = memories[0]

            # Share with each target agent
            shared_count = 0
            for target_id in target_agent_ids:
                try:
                    # Create shared memory entry
                    shared_memory = {
                        "source_agent_id": agent_id,
                        "source_memory_id": memory_id,
                        "shared_at": datetime.utcnow().isoformat(),
                        "permission_level": permission_level.value,
                        "original_content": memory_data["content"],
                        "original_metadata": memory_data["metadata"],
                    }

                    # Store in target agent's memory
                    result = await self.store_agent_memory(
                        agent_id=target_id,
                        memory_type="shared_memory",
                        content=shared_memory,
                        metadata={
                            "shared_from": agent_id,
                            "original_memory_id": memory_id,
                        },
                        permission_level=permission_level,
                    )

                    if result.get("success", False):
                        shared_count += 1
                        logger.info(
                            f"Shared memory {memory_id} from {agent_id} to {target_id}"
                        )
                    else:
                        logger.error(
                            f"Failed to share memory {memory_id} with {target_id}: {result.get('error', 'Unknown error')}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error sharing memory {memory_id} with {target_id}: {e}"
                    )

            logger.info(
                f"Shared memory {memory_id} from {agent_id} to {shared_count}/{len(target_agent_ids)} agents"
            )

            # Record metrics
            if self._metrics_service:
                await self._metrics_service.record_memory_operation(
                    agent_id, "share", "shared_memory"
                )

            return {
                "success": True,
                "memory_id": memory_id,
                "source_agent_id": agent_id,
                "target_agent_ids": target_agent_ids,
                "shared_count": shared_count,
                "permission_level": permission_level.value,
            }

        except Exception as e:
            logger.error(f"Error sharing memory {memory_id} from agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def consolidate_agent_memories(
        self,
        agent_id: str,
        memory_type: Optional[str] = None,
        time_range: Optional[Tuple[datetime, datetime]] = None,
    ) -> Dict[str, Any]:
        """
        Consolidate agent memories using memory fusion service.

        Args:
            agent_id: ID of the agent
            memory_type: Optional memory type to consolidate
            time_range: Optional time range for memories to consolidate

        Returns:
            Result of memory consolidation operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Get memories to consolidate
            memory_result = await self.retrieve_agent_memory(
                agent_id=agent_id,
                memory_type=memory_type,
                limit=100,  # Get more memories for consolidation
            )

            if not memory_result.get("success", False):
                return {
                    "success": False,
                    "error": f"Failed to retrieve memories for agent {agent_id}",
                }

            memories = memory_result.get("memories", [])
            if not memories:
                return {
                    "success": True,
                    "message": "No memories to consolidate",
                    "consolidated_count": 0,
                }

            # Filter by time range if specified
            if time_range:
                start_time, end_time = time_range
                memories = [
                    mem
                    for mem in memories
                    if "timestamp" in mem
                    and start_time
                    <= datetime.fromisoformat(mem["timestamp"])
                    <= end_time
                ]

            if not memories:
                return {
                    "success": True,
                    "message": "No memories in specified time range",
                    "consolidated_count": 0,
                }

            # Use memory fusion service to consolidate
            if self._agent_memory_fusion:
                fusion_result = await self._agent_memory_fusion.consolidate_memories(
                    agent_id=agent_id, memories=memories, memory_type=memory_type
                )

                if fusion_result.get("success", False):
                    consolidated_memory = fusion_result.get("consolidated_memory")

                    # Store the consolidated memory
                    result = await self.store_agent_memory(
                        agent_id=agent_id,
                        memory_type=f"consolidated_{memory_type or 'memory'}",
                        content=consolidated_memory,
                        metadata={
                            "consolidated_at": datetime.utcnow().isoformat(),
                            "source_memories": [
                                mem.get("memory_id") for mem in memories
                            ],
                            "original_memory_type": memory_type,
                        },
                        permission_level=agent_schemas.PermissionLevel.READ,
                    )

                    if result.get("success", False):
                        logger.info(
                            f"Consolidated {len(memories)} memories for agent {agent_id}"
                        )

                        # Record metrics
                        if self._metrics_service:
                            await self._metrics_service.record_memory_operation(
                                agent_id, "consolidate", memory_type or "all"
                            )

                        return {
                            "success": True,
                            "agent_id": agent_id,
                            "memory_type": memory_type,
                            "source_count": len(memories),
                            "consolidated_memory_id": result.get("memory_id"),
                            "consolidated_count": 1,
                        }
                    else:
                        logger.error(
                            f"Failed to store consolidated memory for agent {agent_id}: {result.get('error', 'Unknown error')}"
                        )
                        return {
                            "success": False,
                            "error": "Failed to store consolidated memory",
                        }
                else:
                    logger.error(
                        f"Memory fusion failed for agent {agent_id}: {fusion_result.get('error', 'Unknown error')}"
                    )
                    return {"success": False, "error": "Memory fusion failed"}
            else:
                logger.warning("Agent memory fusion service not available")
                return {
                    "success": False,
                    "error": "Memory fusion service not available",
                }

        except Exception as e:
            logger.error(f"Error consolidating memories for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    # Agent Coordination and Team Management Methods

    async def create_agent_team(
        self,
        team_id: str,
        name: str,
        description: str,
        agent_ids: List[str],
        team_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a team of agents for collaborative tasks with integrated memory and reasoning.

        Args:
            team_id: Unique identifier for the team
            name: Human-readable name of the team
            description: Description of the team's purpose
            agent_ids: List of agent IDs to include in the team
            team_config: Optional configuration for the team

        Returns:
            Result of team creation operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate all agents exist
        async with self._agents_lock:
            for agent_id in agent_ids:
                if agent_id not in self._agents:
                    return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if team already exists
            if team_id in self._agent_teams:
                return {"success": False, "error": f"Team {team_id} already exists"}

            # Create team with enhanced capabilities
            team_info = {
                "team_id": team_id,
                "name": name,
                "description": description,
                "agent_ids": agent_ids,
                "config": team_config or {},
                "created_at": datetime.utcnow().isoformat(),
                "status": "active",
                "tasks": [],
                "current_task": None,
                "shared_memory_id": None,  # For team shared memory
                "reasoning_model": "gpt-4",  # Default reasoning model for team
                "consensus_threshold": 0.7,  # Default consensus threshold
            }

            # Create shared memory space for the team
            shared_memory_result = await self.store_agent_memory(
                agent_id="team_orchestrator",
                memory_type="team_shared",
                content={
                    "team_id": team_id,
                    "name": name,
                    "description": description,
                    "agent_ids": agent_ids,
                    "created_at": datetime.utcnow().isoformat(),
                },
                metadata={"team_id": team_id, "access_level": "team_members"},
                permission_level=agent_schemas.PermissionLevel.WRITE,
            )

            if shared_memory_result.get("success", False):
                team_info["shared_memory_id"] = shared_memory_result["memory_id"]
                logger.info(
                    f"Created shared memory {team_info['shared_memory_id']} for team {team_id}"
                )
            else:
                logger.warning(
                    f"Failed to create shared memory for team {team_id}: {shared_memory_result.get('error', 'Unknown error')}"
                )

            # Initialize team reasoning context if AI orchestrator is available
            if self._langgraph_orchestrator:
                try:
                    # Create team reasoning context
                    reasoning_context = {
                        "team_id": team_id,
                        "team_name": name,
                        "team_description": description,
                        "agent_ids": agent_ids,
                        "team_config": team_config or {},
                        "created_at": datetime.utcnow().isoformat(),
                    }

                    # Initialize team reasoning with AI orchestrator
                    reasoning_result = await self._langgraph_orchestrator.process_flow(
                        "team_reasoning", reasoning_context
                    )

                    reasoning_result_data = self._flow_result_data(reasoning_result)
                    if reasoning_result_data:
                        team_info["reasoning_context"] = reasoning_result_data
                        logger.info(f"Initialized reasoning context for team {team_id}")
                    else:
                        logger.warning(
                            f"Failed to initialize reasoning context for team {team_id}"
                        )

                except Exception as e:
                    logger.error(f"Error initializing team reasoning context: {e}")

            self._agent_teams[team_id] = team_info

            logger.info(f"Created team {team_id} with {len(agent_ids)} agents")

            # Record metrics
            if self._metrics_service:
                for agent_id in agent_ids:
                    await self._metrics_service.record_session_start(agent_id)

            return {
                "success": True,
                "team_id": team_id,
                "name": name,
                "agent_count": len(agent_ids),
                "shared_memory_id": team_info["shared_memory_id"],
                "reasoning_initialized": "reasoning_context" in team_info,
            }

        except Exception as e:
            logger.error(f"Error creating team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def assign_agent_roles(
        self, team_id: str, role_assignments: Dict[str, AgentRole]
    ) -> Dict[str, Any]:
        """
        Assign roles to agents within a team.

        Args:
            team_id: ID of the team
            role_assignments: Dictionary mapping agent IDs to roles

        Returns:
            Result of role assignment operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate team exists
        if team_id not in self._agent_teams:
            return {"success": False, "error": f"Team {team_id} not found"}

        try:
            team = self._agent_teams[team_id]

            # Validate all agents exist in the team
            for agent_id in role_assignments:
                if agent_id not in team["agent_ids"]:
                    return {
                        "success": False,
                        "error": f"Agent {agent_id} not in team {team_id}",
                    }

            # Assign roles
            if "roles" not in team:
                team["roles"] = {}

            for agent_id, role in role_assignments.items():
                team["roles"][agent_id] = (
                    role.value if isinstance(role, AgentRole) else role
                )

            logger.info(
                f"Assigned roles to {len(role_assignments)} agents in team {team_id}"
            )

            return {
                "success": True,
                "team_id": team_id,
                "role_count": len(role_assignments),
            }

        except Exception as e:
            logger.error(f"Error assigning roles in team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def delegate_task_to_team(
        self, team_id: str, task_type: str, task_data: Dict[str, Any], priority: int = 0
    ) -> Dict[str, Any]:
        """
        Delegate a task to a team of agents.

        Args:
            team_id: ID of the team
            task_type: Type of task
            task_data: Data for task execution
            priority: Task priority

        Returns:
            Result of task delegation
        """
        if not self._initialized:
            await self.initialize()

        # Validate team exists
        if team_id not in self._agent_teams:
            return {"success": False, "error": f"Team {team_id} not found"}

        try:
            team = self._agent_teams[team_id]

            # Create team task
            team_task_id = str(uuid.uuid4())
            team_task = {
                "team_task_id": team_task_id,
                "team_id": team_id,
                "task_type": task_type,
                "task_data": task_data,
                "priority": priority,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
                "subtasks": {},
                "results": {},
            }

            # Add to team's task list
            team["tasks"].append(team_task_id)

            # Determine task distribution strategy
            strategy = team["config"].get("task_distribution", "coordinator")

            if strategy == "coordinator":
                # Assign to coordinator agent
                coordinator_id = None
                if "roles" in team:
                    for agent_id, role in team["roles"].items():
                        if role == AgentRole.COORDINATOR:
                            coordinator_id = agent_id
                            break

                if coordinator_id:
                    # Create task for coordinator
                    result = await self.create_task(
                        task_type=task_type,
                        task_data={
                            **task_data,
                            "team_task_id": team_task_id,
                            "team_id": team_id,
                            "agent_ids": team["agent_ids"],
                        },
                        agent_id=coordinator_id,
                        priority=priority,
                    )

                    if result["success"]:
                        team["current_task"] = team_task_id
                        team_task["status"] = "assigned"
                        team_task["coordinator_task_id"] = result["task_id"]

                        logger.info(
                            f"Delegated task {team_task_id} to team {team_id} via coordinator {coordinator_id}"
                        )

                        return {
                            "success": True,
                            "team_task_id": team_task_id,
                            "team_id": team_id,
                            "coordinator_id": coordinator_id,
                            "task_id": result["task_id"],
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to create task for coordinator: {result.get('error', 'Unknown error')}",
                        }
                else:
                    return {
                        "success": False,
                        "error": "No coordinator agent found in team",
                    }

            elif strategy == "parallel":
                # Assign to all agents in parallel
                subtask_ids = []
                for agent_id in team["agent_ids"]:
                    result = await self.create_task(
                        task_type=task_type,
                        task_data={
                            **task_data,
                            "team_task_id": team_task_id,
                            "team_id": team_id,
                            "agent_role": team["roles"].get(agent_id, "worker"),
                        },
                        agent_id=agent_id,
                        priority=priority,
                    )

                    if result["success"]:
                        subtask_ids.append((agent_id, result["task_id"]))
                        team_task["subtasks"][agent_id] = result["task_id"]
                    else:
                        logger.warning(
                            f"Failed to create task for agent {agent_id}: {result.get('error', 'Unknown error')}"
                        )

                if subtask_ids:
                    team["current_task"] = team_task_id
                    team_task["status"] = "assigned"

                    logger.info(
                        f"Delegated task {team_task_id} to team {team_id} in parallel to {len(subtask_ids)} agents"
                    )

                    return {
                        "success": True,
                        "team_task_id": team_task_id,
                        "team_id": team_id,
                        "subtask_count": len(subtask_ids),
                        "subtask_ids": subtask_ids,
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to create tasks for any agent in team",
                    }

            else:
                return {
                    "success": False,
                    "error": f"Unknown task distribution strategy: {strategy}",
                }

        except Exception as e:
            logger.error(f"Error delegating task to team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def negotiate_agent_consensus(
        self,
        team_id: str,
        topic: str,
        proposal: Dict[str, Any],
        timeout_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        Facilitate consensus negotiation among agents in a team using AI Orchestrator.

        Args:
            team_id: ID of the team
            topic: Topic for negotiation
            proposal: Initial proposal
            timeout_seconds: Timeout for negotiation

        Returns:
            Result of consensus negotiation
        """
        if not self._initialized:
            await self.initialize()

        # Validate team exists
        if team_id not in self._agent_teams:
            return {"success": False, "error": f"Team {team_id} not found"}

        try:
            team = self._agent_teams[team_id]

            # Create negotiation session
            negotiation_id = str(uuid.uuid4())
            negotiation = {
                "negotiation_id": negotiation_id,
                "team_id": team_id,
                "topic": topic,
                "initial_proposal": proposal,
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
                "responses": {},
                "consensus": None,
                "timeout_at": (
                    datetime.utcnow() + timedelta(seconds=timeout_seconds)
                ).isoformat(),
                "langgraph_orchestrator_used": False,
            }

            # Use AI Orchestrator for consensus negotiation if available
            if self._langgraph_orchestrator:
                try:
                    # Prepare negotiation context with team information
                    negotiation_context = {
                        "team_id": team_id,
                        "team_name": team["name"],
                        "team_description": team["description"],
                        "agent_ids": team["agent_ids"],
                        "topic": topic,
                        "initial_proposal": proposal,
                        "consensus_threshold": team.get("consensus_threshold", 0.7),
                        "created_at": negotiation["created_at"],
                    }

                    # Add team shared memory context if available
                    if team.get("shared_memory_id"):
                        shared_memory = await self.access_team_shared_memory(
                            team_id=team_id,
                            agent_id="team_orchestrator",
                            limit=5,  # Get recent shared memories
                        )

                        if shared_memory.get("success", False):
                            negotiation_context["shared_memories"] = shared_memory.get(
                                "memories", []
                            )

                    flow_input = negotiation_context

                    # Use AI Orchestrator for consensus negotiation
                    consensus_flow = await self._langgraph_orchestrator.process_flow(
                        "consensus_negotiation", flow_input
                    )

                    consensus_result = self._flow_result_data(consensus_flow)
                    if consensus_result:

                        # Extract consensus information from AI Orchestrator
                        negotiation["consensus"] = consensus_result.get("consensus")
                        negotiation["status"] = (
                            "consensus_reached"
                            if consensus_result.get("consensus")
                            else "no_consensus"
                        )
                        negotiation["langgraph_orchestrator_used"] = True
                        negotiation["ai_confidence"] = consensus_result.get(
                            "confidence", 0.0
                        )
                        negotiation["ai_reasoning"] = consensus_result.get(
                            "reasoning", ""
                        )

                        logger.info(
                            f"AI Orchestrator reached consensus for team {team_id} with confidence {negotiation['ai_confidence']}"
                        )

                        # Store consensus negotiation in team shared memory if available
                        if team.get("shared_memory_id"):
                            memory_result = await self.store_agent_memory(
                                agent_id="team_orchestrator",
                                memory_type="consensus_negotiation",
                                content={
                                    "negotiation_id": negotiation_id,
                                    "team_id": team_id,
                                    "topic": topic,
                                    "initial_proposal": proposal,
                                    "consensus": negotiation["consensus"],
                                    "confidence": negotiation["ai_confidence"],
                                    "reasoning": negotiation["ai_reasoning"],
                                    "negotiated_at": datetime.utcnow().isoformat(),
                                },
                                metadata={
                                    "team_id": team_id,
                                    "negotiation_id": negotiation_id,
                                    "langgraph_orchestrator_used": True,
                                    "consensus_threshold": team.get(
                                        "consensus_threshold", 0.7
                                    ),
                                },
                                permission_level=agent_schemas.PermissionLevel.WRITE,
                            )

                            if memory_result.get("success", False):
                                logger.info(
                                    f"Stored consensus negotiation in team shared memory for team {team_id}"
                                )

                        # Notify agents of consensus
                        for agent_id in team["agent_ids"]:
                            message = {
                                "negotiation_id": negotiation_id,
                                "topic": topic,
                                "consensus": negotiation["consensus"],
                                "confidence": negotiation["ai_confidence"],
                                "reasoning": negotiation["ai_reasoning"],
                            }

                            await self.send_message(
                                sender_id="orchestrator",
                                recipient_id=agent_id,
                                message_type="consensus_reached",
                                content=message,
                            )

                        return {
                            "success": True,
                            "negotiation_id": negotiation_id,
                            "team_id": team_id,
                            "status": negotiation["status"],
                            "consensus": negotiation["consensus"],
                            "langgraph_orchestrator_used": True,
                            "confidence": negotiation["ai_confidence"],
                            "reasoning": negotiation["ai_reasoning"],
                            "response_count": len(team["agent_ids"]),
                        }
                    else:
                        logger.warning(
                            f"AI Orchestrator consensus negotiation failed: {consensus_result.get('message', 'Unknown error')}"
                        )
                        # Fall back to manual negotiation
                        negotiation["langgraph_orchestrator_used"] = False

                except Exception as e:
                    logger.error(
                        f"Error using AI Orchestrator for consensus negotiation: {e}"
                    )
                    # Fall back to manual negotiation
                    negotiation["langgraph_orchestrator_used"] = False

            # Fallback: Manual consensus negotiation process
            # Send negotiation request to all agents
            for agent_id in team["agent_ids"]:
                message = {
                    "negotiation_id": negotiation_id,
                    "topic": topic,
                    "proposal": proposal,
                    "deadline": negotiation["timeout_at"],
                }

                result = await self.send_message(
                    sender_id="orchestrator",
                    recipient_id=agent_id,
                    message_type="negotiation_request",
                    content=message,
                )

                if not result["success"]:
                    logger.warning(
                        f"Failed to send negotiation request to agent {agent_id}"
                    )

            # Wait for responses or timeout
            start_time = datetime.utcnow()
            while True:
                # Check if all agents responded
                if len(negotiation["responses"]) >= len(team["agent_ids"]):
                    negotiation["status"] = "completed"
                    break

                # Check timeout
                if (datetime.utcnow() - start_time).total_seconds() > timeout_seconds:
                    negotiation["status"] = "timeout"
                    break

                await asyncio.sleep(0.1)

            # Analyze responses for consensus
            if negotiation["status"] == "completed":
                # Simple consensus: all agents agree
                responses = list(negotiation["responses"].values())
                if all(response == responses[0] for response in responses):
                    negotiation["consensus"] = responses[0]
                    negotiation["status"] = "consensus_reached"
                else:
                    negotiation["status"] = "no_consensus"

            # Store manual negotiation in team shared memory if available
            if team.get("shared_memory_id"):
                memory_result = await self.store_agent_memory(
                    agent_id="team_orchestrator",
                    memory_type="consensus_negotiation",
                    content={
                        "negotiation_id": negotiation_id,
                        "team_id": team_id,
                        "topic": topic,
                        "initial_proposal": proposal,
                        "responses": negotiation["responses"],
                        "status": negotiation["status"],
                        "consensus": negotiation["consensus"],
                        "negotiated_at": datetime.utcnow().isoformat(),
                    },
                    metadata={
                        "team_id": team_id,
                        "negotiation_id": negotiation_id,
                        "langgraph_orchestrator_used": False,
                    },
                    permission_level=agent_schemas.PermissionLevel.WRITE,
                )

                if memory_result.get("success", False):
                    logger.info(
                        f"Stored consensus negotiation in team shared memory for team {team_id}"
                    )

            logger.info(
                f"Negotiation {negotiation_id} for team {team_id} completed with status: {negotiation['status']}"
            )

            return {
                "success": True,
                "negotiation_id": negotiation_id,
                "team_id": team_id,
                "status": negotiation["status"],
                "consensus": negotiation.get("consensus"),
                "langgraph_orchestrator_used": negotiation["langgraph_orchestrator_used"],
                "response_count": len(negotiation["responses"]),
            }

        except Exception as e:
            logger.error(f"Error in consensus negotiation for team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def access_team_shared_memory(
        self,
        team_id: str,
        agent_id: str,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Access shared memory for an agent team.

        Args:
            team_id: ID of the team
            agent_id: ID of the agent accessing the memory
            query: Optional search query
            memory_type: Optional memory type to filter by
            limit: Maximum number of memories to retrieve

        Returns:
            Result of shared memory access operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate team exists
        if team_id not in self._agent_teams:
            return {"success": False, "error": f"Team {team_id} not found"}

        # Validate agent exists and is part of the team
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

            team = self._agent_teams[team_id]
            if agent_id not in team["agent_ids"]:
                return {
                    "success": False,
                    "error": f"Agent {agent_id} is not a member of team {team_id}",
                }

        try:
            # Check if team has shared memory
            shared_memory_id = team.get("shared_memory_id")
            if not shared_memory_id:
                return {
                    "success": False,
                    "error": f"Team {team_id} does not have shared memory",
                }

            # Access shared memory
            if query:
                # Search shared memories
                result = await self.search_agent_memories(
                    agent_id="team_orchestrator",
                    query=query,
                    memory_type=memory_type,
                    limit=limit,
                )

                # Filter results to only include memories for this team
                memories = [
                    mem
                    for mem in result.get("results", [])
                    if mem.get("metadata", {}).get("team_id") == team_id
                ]

                return {
                    "success": True,
                    "team_id": team_id,
                    "agent_id": agent_id,
                    "query": query,
                    "memories": memories,
                    "count": len(memories),
                }
            else:
                # Retrieve shared memories
                result = await self.retrieve_agent_memory(
                    agent_id="team_orchestrator", memory_type=memory_type, limit=limit
                )

                # Filter results to only include memories for this team
                memories = [
                    mem
                    for mem in result.get("memories", [])
                    if mem.get("metadata", {}).get("team_id") == team_id
                ]

                return {
                    "success": True,
                    "team_id": team_id,
                    "agent_id": agent_id,
                    "memory_type": memory_type,
                    "memories": memories,
                    "count": len(memories),
                }

        except Exception as e:
            logger.error(f"Error accessing shared memory for team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def contribute_to_team_shared_memory(
        self,
        team_id: str,
        agent_id: str,
        memory_type: str,
        content: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Contribute to shared memory for an agent team.

        Args:
            team_id: ID of the team
            agent_id: ID of the agent contributing the memory
            memory_type: Type of memory
            content: Memory content
            metadata: Optional metadata

        Returns:
            Result of memory contribution operation
        """
        if not self._initialized:
            await self.initialize()

        # Validate team exists
        if team_id not in self._agent_teams:
            return {"success": False, "error": f"Team {team_id} not found"}

        # Validate agent exists and is part of the team
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

            team = self._agent_teams[team_id]
            if agent_id not in team["agent_ids"]:
                return {
                    "success": False,
                    "error": f"Agent {agent_id} is not a member of team {team_id}",
                }

        try:
            # Check if team has shared memory
            shared_memory_id = team.get("shared_memory_id")
            if not shared_memory_id:
                return {
                    "success": False,
                    "error": f"Team {team_id} does not have shared memory",
                }

            # Prepare memory content with contribution info
            enhanced_content = {
                "contributor_agent_id": agent_id,
                "team_id": team_id,
                "contribution_timestamp": datetime.utcnow().isoformat(),
                "content": content,
            }

            # Prepare metadata with team information
            enhanced_metadata = {
                "team_id": team_id,
                "contributor_agent_id": agent_id,
                "memory_type": memory_type,
                **(metadata or {}),
            }

            # Store in team shared memory
            result = await self.store_agent_memory(
                agent_id="team_orchestrator",
                memory_type=f"team_contribution_{memory_type}",
                content=enhanced_content,
                metadata=enhanced_metadata,
                permission_level=agent_schemas.PermissionLevel.WRITE,
            )

            if result.get("success", False):
                logger.info(
                    f"Agent {agent_id} contributed to shared memory of team {team_id}"
                )

                return {
                    "success": True,
                    "team_id": team_id,
                    "agent_id": agent_id,
                    "memory_id": result.get("memory_id"),
                    "memory_type": memory_type,
                }
            else:
                return {
                    "success": False,
                    "error": result.get(
                        "error", "Failed to contribute to team shared memory"
                    ),
                }

        except Exception as e:
            logger.error(f"Error contributing to shared memory for team {team_id}: {e}")
            return {"success": False, "error": str(e)}

    async def resolve_agent_conflict(
        self, agent_ids: List[str], conflict_type: str, conflict_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve conflicts between agents using AI Orchestrator.

        Args:
            agent_ids: List of agents in conflict
            conflict_type: Type of conflict
            conflict_details: Details about conflict

        Returns:
            Result of conflict resolution
        """
        if not self._initialized:
            await self.initialize()

        # Validate all agents exist
        async with self._agents_lock:
            for agent_id in agent_ids:
                if agent_id not in self._agents:
                    return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Create conflict resolution session
            resolution_id = str(uuid.uuid4())
            resolution = {
                "resolution_id": resolution_id,
                "agent_ids": agent_ids,
                "conflict_type": conflict_type,
                "conflict_details": conflict_details,
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
                "proposed_solutions": {},
                "resolution": None,
            }

            # Check if conflicting agents are in the same team
            team_id = None
            team_info = None
            for tid, team in self._agent_teams.items():
                if all(agent_id in team["agent_ids"] for agent_id in agent_ids):
                    team_id = tid
                    team_info = team
                    break

            # Use AI orchestrator for conflict resolution if available
            if self._langgraph_orchestrator:
                try:
                    # Prepare conflict context with team information if available
                    conflict_context = {
                        "conflict_type": conflict_type,
                        "conflict_details": conflict_details,
                        "agent_ids": agent_ids,
                    }

                    # Add team context if agents are in the same team
                    if team_id:
                        conflict_context.update(
                            {
                                "team_id": team_id,
                                "team_name": team_info["name"],
                                "team_description": team_info["description"],
                                "shared_memory_id": team_info.get("shared_memory_id"),
                            }
                        )

                    flow_input = conflict_context

                    flow_output = await self._langgraph_orchestrator.process_flow(
                        "conflict_resolution", flow_input
                    )

                    resolution_data = self._flow_result_data(flow_output)
                    if resolution_data:
                        resolution["resolution"] = resolution_data
                        resolution["status"] = "resolved"
                        resolution["resolved_at"] = datetime.utcnow().isoformat()
                        resolution["langgraph_orchestrator_used"] = True

                        logger.info(
                            f"Resolved conflict {resolution_id} using AI orchestrator"
                        )

                        # Store conflict resolution in team shared memory if available
                        if team_id and team_info and team_info.get("shared_memory_id"):
                            memory_result = await self.store_agent_memory(
                                agent_id="team_orchestrator",
                                memory_type="conflict_resolution",
                                content={
                                    "resolution_id": resolution_id,
                                    "team_id": team_id,
                                    "conflict_type": conflict_type,
                                    "conflict_details": conflict_details,
                                    "resolution": resolution_data,
                                    "resolved_at": resolution["resolved_at"],
                                },
                                metadata={
                                    "team_id": team_id,
                                    "resolution_id": resolution_id,
                                    "langgraph_orchestrator_used": True,
                                },
                                permission_level=PermissionLevel.WRITE,
                            )

                            if memory_result.get("success", False):
                                logger.info(
                                    f"Stored conflict resolution in team shared memory for team {team_id}"
                                )

                        # Notify agents of resolution
                        for agent_id in agent_ids:
                            message = {
                                "resolution_id": resolution_id,
                                "resolution": resolution_data,
                            }

                            await self.send_message(
                                sender_id="orchestrator",
                                recipient_id=agent_id,
                                message_type="conflict_resolved",
                                content=message,
                            )

                        return {
                            "success": True,
                            "resolution_id": resolution_id,
                            "conflict_type": conflict_type,
                            "resolution": resolution_data,
                            "team_id": team_id,
                            "langgraph_orchestrator_used": True,
                        }
                    else:
                        logger.warning(
                            f"AI Orchestrator conflict resolution failed: {self._flow_result_data(flow_output).get('message', 'Unknown error')}"
                        )
                        # Fall back to manual resolution

                except Exception as e:
                    logger.error(
                        f"Error using AI orchestrator for conflict resolution: {e}"
                    )
                    # Fall back to manual resolution

            # Fallback: Manual conflict resolution process
            # Send conflict resolution request to all agents
            for agent_id in agent_ids:
                message = {
                    "resolution_id": resolution_id,
                    "conflict_type": conflict_type,
                    "conflict_details": conflict_details,
                }

                result = await self.send_message(
                    sender_id="orchestrator",
                    recipient_id=agent_id,
                    message_type="conflict_resolution",
                    content=message,
                )

                if not result["success"]:
                    logger.warning(
                        f"Failed to send conflict resolution request to agent {agent_id}"
                    )

            # Fallback: simple voting mechanism
            resolution["status"] = "pending_agent_input"
            resolution["langgraph_orchestrator_used"] = False

            # Store conflict resolution in team shared memory if available
            if team_id and team_info and team_info.get("shared_memory_id"):
                memory_result = await self.store_agent_memory(
                    agent_id="team_orchestrator",
                    memory_type="conflict_resolution",
                    content={
                        "resolution_id": resolution_id,
                        "team_id": team_id,
                        "conflict_type": conflict_type,
                        "conflict_details": conflict_details,
                        "status": "pending_agent_input",
                        "created_at": resolution["created_at"],
                    },
                    metadata={
                        "team_id": team_id,
                        "resolution_id": resolution_id,
                        "langgraph_orchestrator_used": False,
                    },
                    permission_level=PermissionLevel.WRITE,
                )

                if memory_result.get("success", False):
                    logger.info(
                        f"Stored conflict resolution in team shared memory for team {team_id}"
                    )

            logger.info(
                f"Initiated conflict resolution {resolution_id} for {len(agent_ids)} agents"
            )

            return {
                "success": True,
                "resolution_id": resolution_id,
                "conflict_type": conflict_type,
                "status": "pending_agent_input",
                "team_id": team_id,
                "agent_count": len(agent_ids),
                "langgraph_orchestrator_used": False,
            }

        except Exception as e:
            logger.error(f"Error resolving conflict: {e}")
            return {"success": False, "error": str(e)}

    # Agent Reasoning and Decision-Making Methods

    async def agent_reasoning_task(
        self,
        agent_id: str,
        reasoning_type: str,
        reasoning_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform reasoning task using AI orchestrator, model orchestrator, and Karen's AI Orchestrator when available.

        Args:
            agent_id: ID of the agent
            reasoning_type: Type of reasoning (logical, causal, probabilistic)
            reasoning_data: Data for reasoning
            context: Optional context for reasoning

        Returns:
            Result of reasoning task
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if AI orchestrator is available
            if not self._langgraph_orchestrator:
                return {"success": False, "error": "AI orchestrator not available"}

            # Select appropriate model for reasoning task
            model_id = await self.select_model_for_task("reasoning", agent_id)

            # Prepare reasoning input
            reasoning_input = {
                "agent_id": agent_id,
                "reasoning_type": reasoning_type,
                "reasoning_data": reasoning_data,
                "context": context or {},
                "model_id": model_id,
            }

            # Get agent's Karen integration configuration if available
            karen_integration_config = None
            karen_reasoning_result = None

            # Check if Karen's system integration is enabled
            if self._karen_integration_enabled:
                async with self._agents_lock:
                    agent_def = self._agents.get(agent_id)
                    if agent_def and "karen_integration" in agent_def.config:
                        karen_integration_config = agent_def.config["karen_integration"]

            # Use Model Orchestrator to run the reasoning model if available
            if self._model_orchestrator:
                try:
                    # Convert reasoning input to model input
                    model_input = {
                        "task_type": "reasoning",
                        "reasoning_type": reasoning_type,
                        "reasoning_data": reasoning_data,
                        "context": context or {},
                    }

                    # Run model using Model Orchestrator
                    model_result = await self.run_model_for_agent(
                        agent_id=agent_id,
                        task_type="reasoning",
                        input_data=model_input,
                        model_id=model_id,
                    )

                    if model_result.get("success", False):
                        # Extract reasoning result from model output
                        model_output = model_result.get("result", {}).get("output", {})
                        reasoning_text = model_output.get("text", "")

                        # Use AI orchestrator to process the model output
                        reasoning_result = (
                            await self._langgraph_orchestrator.complex_reasoning_task(
                                reasoning_type=reasoning_type,
                                data={
                                    "agent_id": agent_id,
                                    "reasoning_data": reasoning_data,
                                    "model_output": reasoning_text,
                                    "context": context or {},
                                },
                            )
                        )

                        if reasoning_result.get("reasoning") == "error":
                            logger.error(
                                f"AI orchestrator reasoning failed: {reasoning_result.get('message', 'Unknown error')}"
                            )
                            return {
                                "success": False,
                                "error": reasoning_result.get(
                                    "message", "Reasoning failed"
                                ),
                            }

                        # Execute reasoning through Karen's AI Orchestrator if enabled
                        if karen_integration_config and karen_integration_config.get(
                            "enabled", False
                        ):
                            try:
                                # Get the agent's Karen flow type
                                karen_flow_type = karen_integration_config.get(
                                    "flow_type", "reasoning"
                                )

                                # Execute Karen flow for reasoning
                                karen_flow_result = await self.execute_karen_flow(
                                    flow_name=karen_flow_type,
                                    flow_data={
                                        "agent_id": agent_id,
                                        "reasoning_type": reasoning_type,
                                        "reasoning_data": reasoning_data,
                                        "model_output": reasoning_text,
                                        "context": context or {},
                                        "reasoning_result": reasoning_result,
                                    },
                                    agent_id=agent_id,
                                )

                                if karen_flow_result.get("success", False):
                                    # Extract Karen reasoning result
                                    karen_reasoning_result = karen_flow_result.get(
                                        "result", {}
                                    )

                                    # Combine results from both reasoning systems
                                    if karen_reasoning_result:
                                        # Create combined reasoning result
                                        combined_reasoning = {
                                            "standard_reasoning": reasoning_result,
                                            "karen_reasoning": karen_reasoning_result,
                                            "combined_confidence": (
                                                reasoning_result.get("confidence", 0.0)
                                                + karen_reasoning_result.get(
                                                    "confidence", 0.0
                                                )
                                            )
                                            / 2,
                                            "model_used": model_id,
                                            "karen_flow_used": karen_flow_type,
                                        }

                                        # Use the combined reasoning as the final result
                                        reasoning_result = combined_reasoning
                                        logger.info(
                                            f"Combined reasoning completed for agent {agent_id} using standard and Karen's AI Orchestrator"
                                        )
                                    else:
                                        logger.warning(
                                            f"Karen's AI Orchestrator returned empty result for agent {agent_id}"
                                        )
                                else:
                                    logger.error(
                                        f"Karen's AI Orchestrator reasoning failed: {karen_flow_result.get('error', 'Unknown error')}"
                                    )
                                    # Continue with standard reasoning result

                            except Exception as e:
                                logger.error(
                                    f"Error executing reasoning through Karen's AI Orchestrator: {e}"
                                )
                                # Continue with standard reasoning result

                        # Enhance reasoning result with model information
                        reasoning_result["model_used"] = model_id
                        reasoning_result["model_output"] = reasoning_text

                        logger.info(
                            f"Complex reasoning task completed for agent {agent_id} using model {model_id}"
                        )

                        # Store reasoning result in agent memory
                        await self.store_agent_memory(
                            agent_id=agent_id,
                            memory_type="reasoning_result",
                            content={
                                "reasoning_type": reasoning_type,
                                "reasoning_data": reasoning_data,
                                "result": reasoning_result,
                                "model_used": model_id,
                                "karen_integration": karen_integration_config
                                is not None,
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                            metadata={
                                "reasoning_confidence": reasoning_result.get(
                                    "confidence", 0.0
                                ),
                                "model_id": model_id,
                                "karen_flow_used": karen_integration_config.get(
                                    "flow_type"
                                )
                                if karen_integration_config
                                else None,
                            },
                            permission_level=agent_schemas.PermissionLevel.READ,
                        )

                        return {
                            "success": True,
                            "reasoning_type": reasoning_type,
                            "result": reasoning_result,
                            "confidence": reasoning_result.get("confidence", 0.0),
                            "model_used": model_id,
                            "karen_integration_used": karen_integration_config
                            is not None,
                        }
                    else:
                        logger.error(
                            f"Model execution failed: {model_result.get('error', 'Unknown error')}"
                        )
                        # Fall back to AI orchestrator without model
                        pass

                except Exception as e:
                    logger.error(f"Error using model orchestrator for reasoning: {e}")
                    # Fall back to AI orchestrator without model
                    pass

            # Fallback: Use AI orchestrator directly without model
            reasoning_result = await self._langgraph_orchestrator.complex_reasoning_task(
                reasoning_type=reasoning_type,
                data={
                    "agent_id": agent_id,
                    "reasoning_data": reasoning_data,
                    "context": context or {},
                },
            )

            if reasoning_result.get("reasoning") == "error":
                logger.error(
                    f"AI orchestrator reasoning failed: {reasoning_result.get('message', 'Unknown error')}"
                )
                return {
                    "success": False,
                    "error": reasoning_result.get("message", "Reasoning failed"),
                }

            # Execute reasoning through Karen's AI Orchestrator if enabled (fallback path)
            if karen_integration_config and karen_integration_config.get(
                "enabled", False
            ):
                try:
                    # Get the agent's Karen flow type
                    karen_flow_type = karen_integration_config.get(
                        "flow_type", "reasoning"
                    )

                    # Execute Karen flow for reasoning
                    karen_flow_result = await self.execute_karen_flow(
                        flow_name=karen_flow_type,
                        flow_data={
                            "agent_id": agent_id,
                            "reasoning_type": reasoning_type,
                            "reasoning_data": reasoning_data,
                            "context": context or {},
                            "reasoning_result": reasoning_result,
                        },
                        agent_id=agent_id,
                    )

                    if karen_flow_result.get("success", False):
                        # Extract Karen reasoning result
                        karen_reasoning_result = karen_flow_result.get("result", {})

                        # Combine results from both reasoning systems
                        if karen_reasoning_result:
                            # Create combined reasoning result
                            combined_reasoning = {
                                "standard_reasoning": reasoning_result,
                                "karen_reasoning": karen_reasoning_result,
                                "combined_confidence": (
                                    reasoning_result.get("confidence", 0.0)
                                    + karen_reasoning_result.get("confidence", 0.0)
                                )
                                / 2,
                                "karen_flow_used": karen_flow_type,
                            }

                            # Use the combined reasoning as the final result
                            reasoning_result = combined_reasoning
                            logger.info(
                                f"Combined reasoning completed for agent {agent_id} using standard and Karen's AI Orchestrator (fallback mode)"
                            )
                        else:
                            logger.warning(
                                f"Karen's AI Orchestrator returned empty result for agent {agent_id} (fallback mode)"
                            )
                    else:
                        logger.error(
                            f"Karen's AI Orchestrator reasoning failed: {karen_flow_result.get('error', 'Unknown error')}"
                        )
                        # Continue with standard reasoning result

                except Exception as e:
                    logger.error(
                        f"Error executing reasoning through Karen's AI Orchestrator (fallback mode): {e}"
                    )
                    # Continue with standard reasoning result

            logger.info(
                f"Complex reasoning task completed for agent {agent_id} (fallback mode)"
            )

            # Store reasoning result in agent memory
            await self.store_agent_memory(
                agent_id=agent_id,
                memory_type="reasoning_result",
                content={
                    "reasoning_type": reasoning_type,
                    "reasoning_data": reasoning_data,
                    "result": reasoning_result,
                    "karen_integration": karen_integration_config is not None,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                metadata={
                    "reasoning_confidence": reasoning_result.get("confidence", 0.0),
                    "karen_flow_used": karen_integration_config.get("flow_type")
                    if karen_integration_config
                    else None,
                },
                permission_level=agent_schemas.PermissionLevel.READ,
            )

            return {
                "success": True,
                "reasoning_type": reasoning_type,
                "result": reasoning_result,
                "confidence": reasoning_result.get("confidence", 0.0),
                "karen_integration_used": karen_integration_config is not None,
            }

        except Exception as e:
            logger.error(f"Error in reasoning task for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def agent_decision_making(
        self,
        agent_id: str,
        decision_type: str,
        options: List[Dict[str, Any]],
        criteria: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform decision-making using AI orchestrator.

        Args:
            agent_id: ID of the agent
            decision_type: Type of decision
            options: List of decision options
            criteria: Optional decision criteria

        Returns:
            Result of decision-making
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if AI orchestrator is available
            if not self._langgraph_orchestrator:
                return {"success": False, "error": "AI orchestrator not available"}

            # Use AI orchestrator's decide_action method for decision-making
            try:
                # Create decision input for AI orchestrator
                decision_input = {
                    "agent_id": agent_id,
                    "decision_type": decision_type,
                    "options": options,
                    "criteria": criteria or {},
                    "context": {
                        "timestamp": datetime.utcnow().isoformat(),
                        "agent_capabilities": self._agents[agent_id].config.get(
                            "capabilities", []
                        ),
                    },
                }

                # Use AI orchestrator to make the decision
                decision_result = await self._langgraph_orchestrator.decide_action(
                    decision_input
                )

                decision_result_data = self._flow_result_data(decision_result)

                if decision_result_data:
                    selected_option = decision_result_data.get(
                        "selected_option"
                    ) or decision_result_data.get("action")
                    decision_confidence = decision_result_data.get("confidence", 0.0)
                    decision_reasoning = decision_result_data.get("reasoning", "")

                    logger.info(
                        f"AI orchestrator made decision for agent {agent_id} with confidence {decision_confidence}"
                    )

                    # Store decision in agent memory
                    await self.store_agent_memory(
                        agent_id=agent_id,
                        memory_type="decision",
                        content={
                            "decision_type": decision_type,
                            "options": options,
                            "selected_option": selected_option,
                            "criteria": criteria,
                            "confidence": decision_confidence,
                            "reasoning": decision_reasoning,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        metadata={
                            "decision_confidence": decision_confidence,
                            "langgraph_orchestrator_used": True,
                        },
                        permission_level=agent_schemas.PermissionLevel.READ,
                    )

                    return {
                        "success": True,
                        "decision_type": decision_type,
                        "selected_option": selected_option,
                        "confidence": decision_confidence,
                        "reasoning": decision_reasoning,
                    }
                else:
                    logger.error(
                        f"AI orchestrator decision-making failed: {decision_result_data.get('message', 'Unknown error')}"
                    )
                    return {
                        "success": False,
                        "error": decision_result_data.get("message", "Decision-making failed"),
                    }

            except Exception as e:
                logger.error(f"Error using AI orchestrator for decision-making: {e}")

                # Fallback to task-based decision-making
                task_data = {
                    "agent_id": agent_id,
                    "decision_type": decision_type,
                    "options": options,
                    "criteria": criteria or {},
                }

                # Create task
                task_result = await self.create_task(
                    task_type="decision_making",
                    task_data=task_data,
                    agent_id=agent_id,
                    priority=5,  # High priority for decision-making tasks
                )

                if not task_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to create decision-making task: {task_result.get('error', 'Unknown error')}",
                    }

                # Wait for task completion
                task_id = task_result["task_id"]
                result = await self.route_task("decision_making", task_data)

                if result["status"] == "completed":
                    logger.info(
                        f"Decision-making task {task_id} completed for agent {agent_id}"
                    )

                    # Store decision in agent memory
                    await self.store_agent_memory(
                        agent_id=agent_id,
                        memory_type="decision",
                        content={
                            "decision_type": decision_type,
                            "options": options,
                            "selected_option": result["result"],
                            "criteria": criteria,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        metadata={"task_id": task_id, "langgraph_orchestrator_used": False},
                        permission_level=agent_schemas.PermissionLevel.READ,
                    )

                    return {
                        "success": True,
                        "task_id": task_id,
                        "decision_type": decision_type,
                        "selected_option": result["result"],
                    }
                else:
                    logger.error(
                        f"Decision-making task {task_id} failed with status: {result['status']}"
                    )
                    return {
                        "success": False,
                        "task_id": task_id,
                        "error": result.get("error", "Decision-making task failed"),
                        "status": result["status"],
                    }

        except Exception as e:
            logger.error(f"Error in decision-making for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def agent_learning_task(
        self,
        agent_id: str,
        learning_type: str,
        learning_data: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform learning task using AI orchestrator.

        Args:
            agent_id: ID of the agent
            learning_type: Type of learning
            learning_data: Data for learning
            feedback: Optional feedback for learning

        Returns:
            Result of learning task
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if AI orchestrator is available
            if not self._langgraph_orchestrator:
                return {"success": False, "error": "AI orchestrator not available"}

            # Create learning task
            task_data = {
                "agent_id": agent_id,
                "learning_type": learning_type,
                "learning_data": learning_data,
                "feedback": feedback or {},
            }

            # Create task
            task_result = await self.create_task(
                task_type="learning",
                task_data=task_data,
                agent_id=agent_id,
                priority=3,  # Medium priority for learning tasks
            )

            if not task_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to create learning task: {task_result.get('error', 'Unknown error')}",
                }

            # Wait for task completion
            task_id = task_result["task_id"]
            result = await self.route_task("learning", task_data)

            if result["status"] == "completed":
                logger.info(f"Learning task {task_id} completed for agent {agent_id}")

                # Store learning result in agent memory
                await self.store_agent_memory(
                    agent_id=agent_id,
                    memory_type="learning",
                    content={
                        "learning_type": learning_type,
                        "learning_data": learning_data,
                        "result": result["result"],
                        "feedback": feedback,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    metadata={"task_id": task_id},
                    permission_level=agent_schemas.PermissionLevel.READ,
                )

                return {
                    "success": True,
                    "task_id": task_id,
                    "learning_type": learning_type,
                    "result": result["result"],
                }
            else:
                logger.error(
                    f"Learning task {task_id} failed with status: {result['status']}"
                )
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": result.get("error", "Learning task failed"),
                    "status": result["status"],
                }

        except Exception as e:
            logger.error(f"Error in learning task for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def agent_problem_solving(
        self,
        agent_id: str,
        problem_type: str,
        problem_data: Dict[str, Any],
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform problem-solving using AI orchestrator.

        Args:
            agent_id: ID of the agent
            problem_type: Type of problem
            problem_data: Data about the problem
            constraints: Optional constraints for solution

        Returns:
            Result of problem-solving
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if AI orchestrator is available
            if not self._langgraph_orchestrator:
                return {"success": False, "error": "AI orchestrator not available"}

            # Create problem-solving task
            task_data = {
                "agent_id": agent_id,
                "problem_type": problem_type,
                "problem_data": problem_data,
                "constraints": constraints or {},
            }

            # Create task
            task_result = await self.create_task(
                task_type="problem_solving",
                task_data=task_data,
                agent_id=agent_id,
                priority=5,  # High priority for problem-solving tasks
            )

            if not task_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to create problem-solving task: {task_result.get('error', 'Unknown error')}",
                }

            # Wait for task completion
            task_id = task_result["task_id"]
            result = await self.route_task("problem_solving", task_data)

            if result["status"] == "completed":
                logger.info(
                    f"Problem-solving task {task_id} completed for agent {agent_id}"
                )

                # Store solution in agent memory
                await self.store_agent_memory(
                    agent_id=agent_id,
                    memory_type="problem_solution",
                    content={
                        "problem_type": problem_type,
                        "problem_data": problem_data,
                        "solution": result["result"],
                        "constraints": constraints,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    metadata={"task_id": task_id},
                    permission_level=agent_schemas.PermissionLevel.READ,
                )

                return {
                    "success": True,
                    "task_id": task_id,
                    "problem_type": problem_type,
                    "solution": result["result"],
                }
            else:
                logger.error(
                    f"Problem-solving task {task_id} failed with status: {result['status']}"
                )
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": result.get("error", "Problem-solving task failed"),
                    "status": result["status"],
                }

        except Exception as e:
            logger.error(f"Error in problem-solving for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    # Model Orchestrator Integration Methods

    async def get_available_models(
        self, provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get list of available models from the model orchestrator.

        Args:
            provider: Provider to filter by (if None, returns all models)

        Returns:
            List of available models
        """
        if not self._initialized:
            await self.initialize()

        try:
            if not self._model_orchestrator:
                logger.warning("Model Orchestrator Service not available")
                return []

            models = self._model_orchestrator.get_available_models(provider)
            logger.info(f"Retrieved {len(models)} available models")
            return models

        except Exception as e:
            logger.error(f"Error getting available models: {e}")
            return []

    async def get_agent_model(self, agent_id: str) -> str:
        """
        Get the preferred model for an agent.

        Args:
            agent_id: ID of the agent

        Returns:
            Model ID preferred for the agent
        """
        # Check if agent has a preferred model
        if agent_id in self._model_preferences:
            return self._model_preferences[agent_id]

        # Check if agent definition has a preferred model
        async with self._agents_lock:
            if agent_id in self._agents:
                agent_def = self._agents[agent_id]
                if "preferred_model" in agent_def.config:
                    return agent_def.config["preferred_model"]

        # Use default model
        return self._default_model

    async def set_agent_model(self, agent_id: str, model_id: str) -> bool:
        """
        Set the preferred model for an agent.

        Args:
            agent_id: ID of the agent
            model_id: ID of the model to prefer

        Returns:
            True if successful
        """
        if not self._initialized:
            await self.initialize()

        # Validate model exists
        try:
            if self._model_orchestrator:
                model_info = self._model_orchestrator.get_model_info(model_id)
                if not model_info:
                    logger.error(f"Model {model_id} not found")
                    return False
        except Exception as e:
            logger.error(f"Error validating model {model_id}: {e}")
            return False

        # Set model preference
        self._model_preferences[agent_id] = model_id

        # Update agent configuration if agent exists
        async with self._agents_lock:
            if agent_id in self._agents:
                agent_def = self._agents[agent_id]
                agent_def.config["preferred_model"] = model_id

        logger.info(f"Set model {model_id} for agent {agent_id}")
        return True

    async def select_model_for_task(
        self, task_type: str, agent_id: Optional[str] = None
    ) -> str:
        """
        Select an appropriate model for a task based on requirements.

        Args:
            task_type: Type of task
            agent_id: Optional agent ID

        Returns:
            Selected model ID
        """
        # Get agent's preferred model if specified
        if agent_id:
            preferred_model = await self.get_agent_model(agent_id)
            return preferred_model

        # Select model based on task type
        task_model_mapping = {
            "reasoning": "gpt-4",  # More complex reasoning tasks
            "learning": "gpt-4",  # Learning tasks benefit from larger models
            "conversation": "gpt-3.5-turbo",  # Conversational tasks
            "decision_making": "gpt-4",  # Complex decision making
            "planning": "gpt-4",  # Strategic planning
            "problem_solving": "gpt-4",  # Problem solving
            "analysis": "gpt-4",  # Data analysis
            "summarization": "gpt-3.5-turbo",  # Text summarization
            "generation": "gpt-3.5-turbo",  # Content generation
        }

        # Get model for task type or use default
        return task_model_mapping.get(task_type, self._default_model)

    async def run_model_for_agent(
        self,
        agent_id: str,
        task_type: str,
        input_data: Dict[str, Any],
        model_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Run a model for an agent using the model orchestrator.

        Args:
            agent_id: ID of the agent
            task_type: Type of task
            input_data: Input data for the model
            model_id: Optional specific model to use
            stream: Whether to stream the response

        Returns:
            Model output
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            if not self._model_orchestrator:
                return {
                    "success": False,
                    "error": "Model Orchestrator Service not available",
                }

            # Select model if not specified
            if not model_id:
                model_id = await self.select_model_for_task(task_type, agent_id)

            # Prepare model input
            model_input = {
                "task_type": task_type,
                "agent_id": agent_id,
                "input_data": input_data,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Run model
            result = self._model_orchestrator.run_model(
                model_id=model_id, input_data=model_input, stream=stream
            )

            logger.info(
                f"Ran model {model_id} for agent {agent_id} on task {task_type}"
            )

            # Record metrics using tool usage tracking
            if self._metrics_service:
                await self._metrics_service.record_tool_usage(
                    agent_id=agent_id, tool_id=f"model_{model_id}"
                )

            return {
                "success": True,
                "agent_id": agent_id,
                "task_type": task_type,
                "model_id": model_id,
                "result": result,
            }

        except Exception as e:
            logger.error(f"Error running model for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    async def stream_model_for_agent(
        self,
        agent_id: str,
        task_type: str,
        input_data: Dict[str, Any],
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Stream a model response for an agent.

        Args:
            agent_id: ID of the agent
            task_type: Type of task
            input_data: Input data for the model
            model_id: Optional specific model to use

        Returns:
            Streaming response information
        """
        if not self._initialized:
            await self.initialize()

        # Use the run_model_for_agent method with streaming enabled
        return await self.run_model_for_agent(
            agent_id=agent_id,
            task_type=task_type,
            input_data=input_data,
            model_id=model_id,
            stream=True,
        )

    async def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a model.

        Args:
            model_id: ID of the model

        Returns:
            Model information or None if not found
        """
        if not self._initialized:
            await self.initialize()

        try:
            if not self._model_orchestrator:
                return None

            return self._model_orchestrator.get_model_info(model_id)

        except Exception as e:
            logger.error(f"Error getting model info for {model_id}: {e}")
            return None

    async def agent_planning_task(
        self,
        agent_id: str,
        planning_type: str,
        goal_data: Dict[str, Any],
        resources: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform planning task using AI orchestrator.

        Args:
            agent_id: ID of the agent
            planning_type: Type of planning
            goal_data: Data about the goal
            resources: Optional available resources

        Returns:
            Result of planning task
        """
        if not self._initialized:
            await self.initialize()

        # Validate agent exists
        async with self._agents_lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

        try:
            # Check if AI orchestrator is available
            if not self._langgraph_orchestrator:
                return {"success": False, "error": "AI orchestrator not available"}

            # Create planning task
            task_data = {
                "agent_id": agent_id,
                "planning_type": planning_type,
                "goal_data": goal_data,
                "resources": resources or {},
            }

            # Create task
            task_result = await self.create_task(
                task_type="planning",
                task_data=task_data,
                agent_id=agent_id,
                priority=4,  # Medium-high priority for planning tasks
            )

            if not task_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to create planning task: {task_result.get('error', 'Unknown error')}",
                }

            # Wait for task completion
            task_id = task_result["task_id"]
            result = await self.route_task("planning", task_data)

            if result["status"] == "completed":
                logger.info(f"Planning task {task_id} completed for agent {agent_id}")

                # Store plan in agent memory
                await self.store_agent_memory(
                    agent_id=agent_id,
                    memory_type="plan",
                    content={
                        "planning_type": planning_type,
                        "goal_data": goal_data,
                        "plan": result["result"],
                        "resources": resources,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    metadata={"task_id": task_id},
                    permission_level=agent_schemas.PermissionLevel.READ,
                )

                return {
                    "success": True,
                    "task_id": task_id,
                    "planning_type": planning_type,
                    "plan": result["result"],
                }
            else:
                logger.error(
                    f"Planning task {task_id} failed with status: {result['status']}"
                )
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": result.get("error", "Planning task failed"),
                    "status": result["status"],
                }

        except Exception as e:
            logger.error(f"Error in planning task for agent {agent_id}: {e}")
            return {"success": False, "error": str(e)}

    # Karen Integration Methods

    async def enable_karen_integration(self, enabled: bool = True) -> Dict[str, Any]:
        """
        Enable or disable Karen's system integration.

        Args:
            enabled: Whether to enable Karen integration

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            self._karen_integration_enabled = enabled

            if enabled:
                logger.info("Karen integration enabled")

                # Initialize Karen flow mappings if available
                if not self._karen_flows and self.config.data.get(
                    "karen_integration", {}
                ).get("flow_mappings"):
                    self._karen_flows = self.config.data.get(
                        "karen_integration", {}
                    ).get("flow_mappings", {})
                    logger.info(
                        f"Initialized {len(self._karen_flows)} Karen flow mappings"
                    )

                # Initialize agent-Karen mappings if available
                if not self._agent_karen_mappings and self.config.data.get(
                    "karen_integration", {}
                ).get("agent_mappings"):
                    self._agent_karen_mappings = self.config.data.get(
                        "karen_integration", {}
                    ).get("agent_mappings", {})
                    logger.info(
                        f"Initialized {len(self._agent_karen_mappings)} agent-Karen mappings"
                    )
            else:
                logger.info("Karen integration disabled")

            return {
                "success": True,
                "karen_integration_enabled": self._karen_integration_enabled,
                "flow_mappings_count": len(self._karen_flows),
                "agent_mappings_count": len(self._agent_karen_mappings),
            }

        except Exception as e:
            logger.error(
                f"Error {'enabling' if enabled else 'disabling'} Karen integration: {e}"
            )
            return {"success": False, "error": str(e)}

    async def add_karen_flow_mapping(
        self, flow_name: str, flow_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add a new Karen flow mapping.

        Args:
            flow_name: Name of the flow
            flow_config: Configuration for the flow

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            self._karen_flows[flow_name] = flow_config
            logger.info(f"Added Karen flow mapping: {flow_name}")

            return {"success": True, "flow_name": flow_name, "flow_config": flow_config}

        except Exception as e:
            logger.error(f"Error adding Karen flow mapping {flow_name}: {e}")
            return {"success": False, "error": str(e)}

    async def remove_karen_flow_mapping(self, flow_name: str) -> Dict[str, Any]:
        """
        Remove a Karen flow mapping.

        Args:
            flow_name: Name of the flow to remove

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            if flow_name not in self._karen_flows:
                return {"success": False, "error": f"Flow {flow_name} not found"}

            del self._karen_flows[flow_name]
            logger.info(f"Removed Karen flow mapping: {flow_name}")

            return {"success": True, "flow_name": flow_name}

        except Exception as e:
            logger.error(f"Error removing Karen flow mapping {flow_name}: {e}")
            return {"success": False, "error": str(e)}

    async def add_agent_karen_mapping(
        self, agent_type: str, flow_type: str
    ) -> Dict[str, Any]:
        """
        Add a mapping between an agent type and a Karen flow type.

        Args:
            agent_type: Type of agent
            flow_type: Type of Karen flow

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            self._agent_karen_mappings[agent_type] = flow_type
            logger.info(f"Added agent-Karen mapping: {agent_type} -> {flow_type}")

            return {"success": True, "agent_type": agent_type, "flow_type": flow_type}

        except Exception as e:
            logger.error(
                f"Error adding agent-Karen mapping {agent_type} -> {flow_type}: {e}"
            )
            return {"success": False, "error": str(e)}

    async def remove_agent_karen_mapping(self, agent_type: str) -> Dict[str, Any]:
        """
        Remove a mapping between an agent type and a Karen flow type.

        Args:
            agent_type: Type of agent

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            if agent_type not in self._agent_karen_mappings:
                return {
                    "success": False,
                    "error": f"Agent type {agent_type} not found in mappings",
                }

            flow_type = self._agent_karen_mappings[agent_type]
            del self._agent_karen_mappings[agent_type]
            logger.info(f"Removed agent-Karen mapping: {agent_type} -> {flow_type}")

            return {"success": True, "agent_type": agent_type, "flow_type": flow_type}

        except Exception as e:
            logger.error(f"Error removing agent-Karen mapping for {agent_type}: {e}")
            return {"success": False, "error": str(e)}

    async def execute_karen_flow(
        self,
        flow_name: str,
        flow_data: Dict[str, Any],
        agent_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a Karen flow.

        Args:
            flow_name: Name of the flow to execute
            flow_data: Data for the flow
            agent_id: Optional agent ID associated with the flow
            timeout_seconds: Optional timeout for the flow

        Returns:
            Result of the flow execution
        """
        if not self._initialized:
            await self.initialize()

        if not self._karen_integration_enabled:
            return {"success": False, "error": "Karen integration is disabled"}

        try:
            # Check if flow exists
            if flow_name not in self._karen_flows:
                return {"success": False, "error": f"Flow {flow_name} not found"}

            # Get flow configuration
            flow_config = self._karen_flows[flow_name]

            # Set timeout
            timeout = timeout_seconds or self._karen_flow_timeout

            # Execute flow with retry logic
            flow_id = str(uuid.uuid4())
            start_time = datetime.utcnow()

            for attempt in range(self._karen_max_retries + 1):
                try:
                    # Update metrics
                    self._karen_flows_executed += 1

                    # This is where the actual Karen flow execution would happen
                    # For now, we'll simulate flow execution
                    flow_result = {
                        "flow_id": flow_id,
                        "flow_name": flow_name,
                        "status": "completed",
                        "result": f"Executed flow {flow_name} with data {flow_data}",
                        "executed_at": start_time.isoformat(),
                    }

                    # Calculate execution time
                    execution_time = (datetime.utcnow() - start_time).total_seconds()
                    self._karen_flow_times.append(execution_time)

                    # Update metrics
                    self._karen_flows_completed += 1

                    # Store flow result
                    self._karen_flow_results[flow_id] = {
                        "flow_name": flow_name,
                        "agent_id": agent_id,
                        "status": "completed",
                        "execution_time": execution_time,
                        "timestamp": datetime.utcnow().isoformat(),
                    }

                    logger.info(
                        f"Successfully executed Karen flow {flow_name} (attempt {attempt + 1})"
                    )

                    return {
                        "success": True,
                        "flow_id": flow_id,
                        "flow_name": flow_name,
                        "execution_time": execution_time,
                        "result": flow_result,
                    }

                except Exception as e:
                    logger.warning(
                        f"Karen flow {flow_name} execution failed (attempt {attempt + 1}/{self._karen_max_retries + 1}): {e}"
                    )

                    # If this is the last attempt, mark as failed
                    if attempt == self._karen_max_retries:
                        # Update metrics
                        self._karen_flows_failed += 1

                        # Store flow result
                        self._karen_flow_results[flow_id] = {
                            "flow_name": flow_name,
                            "agent_id": agent_id,
                            "status": "failed",
                            "error": str(e),
                            "timestamp": datetime.utcnow().isoformat(),
                        }

                        logger.error(
                            f"Karen flow {flow_name} execution failed after {self._karen_max_retries + 1} attempts"
                        )

                        return {
                            "success": False,
                            "flow_id": flow_id,
                            "flow_name": flow_name,
                            "error": str(e),
                            "attempts": attempt + 1,
                        }

                    # Wait before retrying
                    await asyncio.sleep(2**attempt)  # Exponential backoff

            # This line should never be reached, but just in case
            return {"success": False, "error": "Unknown error in flow execution"}

        except Exception as e:
            logger.error(f"Error executing Karen flow {flow_name}: {e}")
            return {"success": False, "error": str(e)}

    async def get_karen_flow_status(self, flow_id: str) -> Dict[str, Any]:
        """
        Get the status of a Karen flow.

        Args:
            flow_id: ID of the flow

        Returns:
            Status of the flow
        """
        if not self._initialized:
            await self.initialize()

        try:
            if flow_id not in self._karen_flow_results:
                return {"success": False, "error": f"Flow {flow_id} not found"}

            flow_result = self._karen_flow_results[flow_id]

            return {
                "success": True,
                "flow_id": flow_id,
                "flow_name": flow_result["flow_name"],
                "status": flow_result["status"],
                "agent_id": flow_result.get("agent_id"),
                "execution_time": flow_result.get("execution_time"),
                "error": flow_result.get("error"),
                "timestamp": flow_result["timestamp"],
            }

        except Exception as e:
            logger.error(f"Error getting Karen flow status for {flow_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_karen_integration_status(self) -> Dict[str, Any]:
        """
        Get the status of Karen's system integration.

        Returns:
            Status of Karen integration
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Calculate average Karen flow time
            avg_karen_flow_time = 0.0
            if self._karen_flow_times:
                avg_karen_flow_time = sum(self._karen_flow_times) / len(
                    self._karen_flow_times
                )

            return {
                "success": True,
                "karen_integration_enabled": self._karen_integration_enabled,
                "flow_mappings_count": len(self._karen_flows),
                "agent_mappings_count": len(self._agent_karen_mappings),
                "flow_results_count": len(self._karen_flow_results),
                "flows_executed": self._karen_flows_executed,
                "flows_completed": self._karen_flows_completed,
                "flows_failed": self._karen_flows_failed,
                "avg_flow_time_seconds": avg_karen_flow_time,
                "flow_timeout_seconds": self._karen_flow_timeout,
                "max_retries": self._karen_max_retries,
            }

        except Exception as e:
            logger.error(f"Error getting Karen integration status: {e}")
            return {"success": False, "error": str(e)}

    async def update_karen_integration_config(
        self, flow_timeout: Optional[int] = None, max_retries: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Update Karen integration configuration.

        Args:
            flow_timeout: Optional new flow timeout in seconds
            max_retries: Optional new maximum number of retries

        Returns:
            Result of the configuration update
        """
        if not self._initialized:
            await self.initialize()

        try:
            if flow_timeout is not None:
                self._karen_flow_timeout = flow_timeout
                logger.info(f"Updated Karen flow timeout to {flow_timeout} seconds")

            if max_retries is not None:
                self._karen_max_retries = max_retries
                logger.info(f"Updated Karen max retries to {max_retries}")

            return {
                "success": True,
                "flow_timeout_seconds": self._karen_flow_timeout,
                "max_retries": self._karen_max_retries,
            }

        except Exception as e:
            logger.error(f"Error updating Karen integration config: {e}")
            return {"success": False, "error": str(e)}

    async def get_karen_flow_mappings(self) -> Dict[str, Any]:
        """
        Get all Karen flow mappings.

        Returns:
            All Karen flow mappings
        """
        if not self._initialized:
            await self.initialize()

        try:
            return {
                "success": True,
                "flow_mappings": self._karen_flows,
                "count": len(self._karen_flows),
            }

        except Exception as e:
            logger.error(f"Error getting Karen flow mappings: {e}")
            return {"success": False, "error": str(e)}

    async def get_agent_karen_mappings(self) -> Dict[str, Any]:
        """
        Get all agent-Karen mappings.

        Returns:
            All agent-Karen mappings
        """
        if not self._initialized:
            await self.initialize()

        try:
            return {
                "success": True,
                "agent_mappings": self._agent_karen_mappings,
                "count": len(self._agent_karen_mappings),
            }

        except Exception as e:
            logger.error(f"Error getting agent-Karen mappings: {e}")
            return {"success": False, "error": str(e)}

    async def clear_karen_flow_results(self) -> Dict[str, Any]:
        """
        Clear all Karen flow results.

        Returns:
            Result of the operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            results_count = len(self._karen_flow_results)
            self._karen_flow_results.clear()

            logger.info(f"Cleared {results_count} Karen flow results")

            return {"success": True, "cleared_results_count": results_count}

        except Exception as e:
            logger.error(f"Error clearing Karen flow results: {e}")
            return {"success": False, "error": str(e)}

    async def _karen_integration_processor(self) -> None:
        """
        Background task to process Karen's system integration tasks.

        This method runs continuously to:
        1. Process pending Karen's system integration tasks
        2. Handle flow execution and result processing
        3. Update metrics for Karen's system integration
        """
        # Set flag to indicate processor is running
        self._karen_processor_running = True

        try:
            while True:
                try:
                    if not self._initialized:
                        await asyncio.sleep(1)
                        continue

                    if not self._karen_integration_enabled:
                        self._karen_processor_running = False
                        await asyncio.sleep(
                            10
                        )  # Check every 10 seconds if integration is disabled
                        continue

                    # Set flag to indicate processor is running
                    self._karen_processor_running = True

                    # Log that Karen integration processor is running periodically
                    logger.debug("Karen integration processor running")

                    # Process any pending Karen integration tasks
                    await self._process_pending_karen_tasks()

                    # Handle flow execution and result processing
                    await self._process_karen_flows()

                    # Update metrics for Karen's system integration
                    await self._update_karen_metrics()

                    # Sleep for a short interval before next iteration
                    await asyncio.sleep(5)  # Process every 5 seconds when enabled

                except Exception as e:
                    logger.error(f"Error in Karen integration processor: {e}")
                    self._karen_processor_running = False
                    await asyncio.sleep(5)
        finally:
            # Ensure flag is set to False when processor exits
            self._karen_processor_running = False
            # Also clear the task reference
            self._karen_integration_task = None

    async def _process_pending_karen_tasks(self) -> None:
        """Process any pending Karen's system integration tasks."""
        try:
            # Check if there are any pending tasks that need to be processed
            # This is a placeholder for actual task processing logic
            # In a real implementation, this would check a task queue or database

            # For now, we'll just log that we're checking for pending tasks
            logger.debug("Checking for pending Karen integration tasks")

            # If there were pending tasks, they would be processed here
            # For example:
            # for task in pending_tasks:
            #     await self._execute_karen_integration_task(task)

        except Exception as e:
            logger.error(f"Error processing pending Karen tasks: {e}")

    async def _process_karen_flows(self) -> None:
        """Handle flow execution and result processing for Karen's system integration."""
        try:
            # Check if there are any flows that need to be executed
            # This is a placeholder for actual flow processing logic
            # In a real implementation, this would check a flow queue or database

            # For now, we'll just log that we're checking for flows to execute
            logger.debug("Checking for Karen flows to execute")

            # If there were flows to execute, they would be processed here
            # For example:
            # for flow in pending_flows:
            #     result = await self.execute_karen_flow(flow.name, flow.data)
            #     await self._process_karen_flow_result(result)

        except Exception as e:
            logger.error(f"Error processing Karen flows: {e}")

    async def _update_karen_metrics(self) -> None:
        """Update metrics for Karen's system integration."""
        try:
            # Calculate average flow time
            avg_karen_flow_time = 0.0
            if self._karen_flow_times:
                avg_karen_flow_time = sum(self._karen_flow_times) / len(
                    self._karen_flow_times
                )

            # Log current metrics
            logger.debug(
                f"Karen integration metrics: "
                f"executed={self._karen_flows_executed}, "
                f"completed={self._karen_flows_completed}, "
                f"failed={self._karen_flows_failed}, "
                f"avg_time={avg_karen_flow_time:.2f}s"
            )

            # Update metrics service if available
            if self._metrics_service:
                try:
                    # Record Karen integration metrics using existing methods
                    # We'll record these as tool usage metrics with a special tool ID for Karen integration

                    # Record flows executed as tool usage
                    if self._karen_flows_executed > 0:
                        await self._metrics_service.record_tool_usage(
                            agent_id="karen_integration", tool_id="karen_flows_executed"
                        )

                    # Record flows completed as tool usage
                    if self._karen_flows_completed > 0:
                        await self._metrics_service.record_tool_usage(
                            agent_id="karen_integration",
                            tool_id="karen_flows_completed",
                        )

                    # Record flows failed as tool usage
                    if self._karen_flows_failed > 0:
                        await self._metrics_service.record_tool_usage(
                            agent_id="karen_integration", tool_id="karen_flows_failed"
                        )

                    # Record average flow time as tool execution time
                    if avg_karen_flow_time > 0:
                        await self._metrics_service.record_tool_execution_time(
                            tool_id="karen_avg_flow_time",
                            execution_time=avg_karen_flow_time,
                        )

                    # Calculate and record success rate
                    if self._karen_flows_executed > 0:
                        success_rate = (
                            self._karen_flows_completed / self._karen_flows_executed
                        )
                        # We'll record this as a successful tool operation for the success rate metric
                        if success_rate >= 0.8:  # High success rate
                            await self._metrics_service.record_tool_success(
                                tool_id="karen_success_rate"
                            )
                        else:  # Lower success rate
                            await self._metrics_service.record_tool_failure(
                                tool_id="karen_success_rate"
                            )

                except Exception as e:
                    logger.error(f"Error updating Karen integration metrics: {e}")

        except Exception as e:
            logger.error(f"Error updating Karen metrics: {e}")

    async def start(self) -> Dict[str, Any]:
        """
        Start the Agent Orchestrator service and all integrated components.

        Returns:
            Result of the start operation
        """
        if not self._initialized:
            await self.initialize()

        try:
            logger.info("Starting Agent Orchestrator service")

            # Start Karen's system integration if enabled
            if self._karen_integration_enabled:
                logger.info("Starting Karen's system integration components")

                # Initialize Karen integration processor
                self._karen_integration_task = asyncio.create_task(
                    self._karen_integration_processor()
                )
                logger.info("Karen integration processor started")

                # Log Karen integration status
                logger.info(
                    f"Karen integration enabled with {len(self._karen_flows)} flow mappings and {len(self._agent_karen_mappings)} agent mappings"
                )
            else:
                logger.info(
                    "Karen integration is disabled, skipping initialization of Karen components"
                )

            # Start background tasks if they're not already running
            if (
                not hasattr(self, "_background_tasks_started")
                or not self._background_tasks_started
            ):
                asyncio.create_task(self._task_processor())
                asyncio.create_task(self._message_processor())
                asyncio.create_task(self._session_monitor())
                asyncio.create_task(self._resource_monitor())
                self._background_tasks_started = True
                logger.info("Background tasks started")

            logger.info("Agent Orchestrator service started successfully")

            return {
                "success": True,
                "service": "agent_orchestrator",
                "karen_integration_enabled": self._karen_integration_enabled,
                "flow_mappings_count": len(self._karen_flows),
                "agent_mappings_count": len(self._agent_karen_mappings),
            }

        except Exception as e:
            logger.error(f"Error starting Agent Orchestrator service: {e}")
            return {"success": False, "error": str(e)}

    async def stop(self) -> Dict[str, Any]:
        """
        Stop the Agent Orchestrator service and all integrated components.

        Returns:
            Result of the stop operation
        """
        try:
            logger.info("Stopping Agent Orchestrator service")

            # Initialize variables
            results_count = 0

            # Stop Karen's system integration components if enabled
            if self._karen_integration_enabled:
                logger.info("Stopping Karen's system integration components")

                # Check if the _karen_integration_task is running and cancel it
                if (
                    self._karen_integration_task
                    and not self._karen_integration_task.done()
                ):
                    logger.info("Cancelling Karen integration task")
                    self._karen_integration_task.cancel()

                    try:
                        await self._karen_integration_task
                    except asyncio.CancelledError:
                        logger.info("Karen integration task cancelled successfully")
                    except Exception as e:
                        logger.error(
                            f"Error while cancelling Karen integration task: {e}"
                        )

                    # Set the task to None after cancellation
                    self._karen_integration_task = None

                # Clear Karen flow results
                results_count = len(self._karen_flow_results)
                self._karen_flow_results.clear()
                logger.info(f"Cleared {results_count} Karen flow results")

                # Clean up any Karen's system integration resources
                if self._karen_processor_running:
                    logger.info("Stopping Karen integration processor")
                    self._karen_processor_running = False

                # Log Karen integration shutdown
                logger.info(
                    "Karen's system integration components stopped successfully"
                )
            else:
                logger.info(
                    "Karen integration is disabled, no Karen components to stop"
                )

            # Cancel all active tasks
            async with self._tasks_lock:
                task_ids = list(self._active_tasks.keys())
                for task_id in task_ids:
                    await self._cancel_task(task_id)
                logger.info(f"Cancelled {len(task_ids)} active tasks")

            # Clear message queue
            async with self._messages_lock:
                message_count = len(self._message_queue)
                self._message_queue.clear()
                logger.info(f"Cleared {message_count} queued messages")

            # Terminate all agent instances
            async with self._agents_lock:
                agent_ids = list(self._agents.keys())
                for agent_id in agent_ids:
                    await self._terminate_agent_instance(agent_id)
                logger.info(f"Terminated {len(agent_ids)} agent instances")

            # Release all services
            for service_name in list(self._service_registry.keys()):
                await self._release_service(service_name)

            logger.info("Agent Orchestrator service stopped successfully")

            return {
                "success": True,
                "service": "agent_orchestrator",
                "karen_integration_enabled": self._karen_integration_enabled,
                "cleared_flow_results": results_count,
            }

        except Exception as e:
            logger.error(f"Error stopping Agent Orchestrator service: {e}")
            return {"success": False, "error": str(e)}
