"""
Production MCP Services Factory
Comprehensive factory for initializing and wiring all MCP-related services.
"""

import logging
from typing import Optional, Dict, Any, List
from functools import lru_cache
import time

logger = logging.getLogger(__name__)


class MCPServiceConfig:
    """Configuration for MCP services."""

    def __init__(
        self,
        # Core settings
        enable_grpc: bool = True,
        enable_json_rpc: bool = True,
        enable_service_registry: bool = True,
        # Redis settings
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        use_redis: bool = True,
        # Authentication settings
        default_token: str = "default-token",
        default_role: str = "user",
        enable_rbac: bool = True,
        # Service settings
        enable_knowledge_graph_service: bool = True,
        enable_llm_service: bool = True,
        # Performance settings
        connection_pool_size: int = 10,
        request_timeout: int = 30,
        enable_retry: bool = True,
        max_retries: int = 3,
        retry_backoff_factor: float = 2.0,
        # Resilience settings
        enable_circuit_breaker: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: int = 60,
        # Monitoring settings
        enable_health_checks: bool = True,
        enable_metrics: bool = True,
        health_check_interval: int = 30,
    ):
        self.enable_grpc = enable_grpc
        self.enable_json_rpc = enable_json_rpc
        self.enable_service_registry = enable_service_registry

        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.use_redis = use_redis

        self.default_token = default_token
        self.default_role = default_role
        self.enable_rbac = enable_rbac

        self.enable_knowledge_graph_service = enable_knowledge_graph_service
        self.enable_llm_service = enable_llm_service

        self.connection_pool_size = connection_pool_size
        self.request_timeout = request_timeout
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.retry_backoff_factor = retry_backoff_factor

        self.enable_circuit_breaker = enable_circuit_breaker
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_timeout = circuit_breaker_timeout

        self.enable_health_checks = enable_health_checks
        self.enable_metrics = enable_metrics
        self.health_check_interval = health_check_interval


class MCPServiceFactory:
    """
    Factory for creating and wiring MCP services.

    This factory ensures all MCP services (registry, clients, service wrappers)
    are properly initialized, configured, and wired together for production use.
    """

    def __init__(self, config: Optional[MCPServiceConfig] = None):
        self.config = config or MCPServiceConfig()
        self._services = {}
        self._clients = {}
        self._circuit_breakers = {}
        logger.info("MCPServiceFactory initialized")

    def create_service_registry(self):
        """Create and configure service registry."""
        if not self.config.enable_service_registry:
            logger.info("Service registry disabled by configuration")
            return None

        try:
            from ai_karen_engine.mcp.registry import ServiceRegistry

            if self.config.use_redis:
                try:
                    import redis

                    redis_client = redis.Redis(
                        host=self.config.redis_host,
                        port=self.config.redis_port,
                        db=self.config.redis_db,
                        password=self.config.redis_password,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                    )
                    # Test connection
                    redis_client.ping()
                    registry = ServiceRegistry(redis_client=redis_client)
                    logger.info("Service registry created with Redis backend")
                except Exception as e:
                    logger.warning(f"Redis unavailable, falling back to in-memory: {e}")
                    registry = self._create_in_memory_registry()
            else:
                registry = self._create_in_memory_registry()

            self._services["service_registry"] = registry
            return registry

        except Exception as e:
            logger.error(f"Failed to create service registry: {e}")
            return None

    def _create_in_memory_registry(self):
        """Create in-memory service registry fallback."""
        from ai_karen_engine.mcp.registry import InMemoryServiceRegistry

        logger.info("Using in-memory service registry")
        return InMemoryServiceRegistry()

    def create_grpc_client(self):
        """Create and configure gRPC client."""
        if not self.config.enable_grpc:
            logger.info("gRPC client disabled by configuration")
            return None

        try:
            from ai_karen_engine.mcp.grpc_client import GRPCClient

            # Get or create registry
            registry = self.get_service("service_registry")
            if not registry:
                registry = self.create_service_registry()

            if not registry:
                logger.error("Cannot create gRPC client: registry unavailable")
                return None

            client = GRPCClient(
                registry=registry,
                token=self.config.default_token,
                role=self.config.default_role,
            )

            # Wrap with retry logic if enabled
            if self.config.enable_retry:
                client = self._wrap_with_retry(client, "grpc")

            # Wrap with circuit breaker if enabled
            if self.config.enable_circuit_breaker:
                client = self._wrap_with_circuit_breaker(client, "grpc")

            self._clients["grpc_client"] = client
            logger.info("gRPC client created successfully")
            return client

        except Exception as e:
            logger.error(f"Failed to create gRPC client: {e}")
            return None

    def create_json_rpc_client(self):
        """Create and configure JSON-RPC client."""
        if not self.config.enable_json_rpc:
            logger.info("JSON-RPC client disabled by configuration")
            return None

        try:
            from ai_karen_engine.mcp.json_rpc_client import JSONRPCClient

            # Get or create registry
            registry = self.get_service("service_registry")
            if not registry:
                registry = self.create_service_registry()

            if not registry:
                logger.error("Cannot create JSON-RPC client: registry unavailable")
                return None

            client = JSONRPCClient(
                registry=registry,
                token=self.config.default_token,
                role=self.config.default_role,
            )

            # Wrap with retry logic if enabled
            if self.config.enable_retry:
                client = self._wrap_with_retry(client, "jsonrpc")

            # Wrap with circuit breaker if enabled
            if self.config.enable_circuit_breaker:
                client = self._wrap_with_circuit_breaker(client, "jsonrpc")

            self._clients["json_rpc_client"] = client
            logger.info("JSON-RPC client created successfully")
            return client

        except Exception as e:
            logger.error(f"Failed to create JSON-RPC client: {e}")
            return None

    def create_knowledge_graph_service(self):
        """Do not register a raw, unscoped graph execution service.

        Memory graph evidence is available only through the canonical runtime's
        authorized recall path, not an MCP Cypher endpoint.
        """
        if not self.config.enable_knowledge_graph_service:
            logger.info("Legacy graph MCP endpoint disabled by configuration")
            return None

        # This historical configuration flag does not grant authorization.
        # Fail closed without constructing an independent database client or
        # registering an MCP service with permissive default roles.
        logger.warning(
            "mcp.legacy_graph_service.disabled",
            extra={"reason": "canonical_memory_authority_required"},
        )
        return None

    def create_llm_service(self):
        """Create and configure LLM service."""
        if not self.config.enable_llm_service:
            logger.info("LLM service disabled by configuration")
            return None

        try:
            from ai_karen_engine.mcp.services import LLMService
            from ai_karen_engine.integrations.llm_utils import LLMUtils

            # Get or create registry
            registry = self.get_service("service_registry")
            if not registry:
                registry = self.create_service_registry()

            if not registry:
                logger.error("Cannot create LLM service: registry unavailable")
                return None

            # Create LLM utils
            try:
                llm = LLMUtils()
            except Exception as e:
                logger.warning(f"LLMUtils unavailable: {e}")
                return None

            service = LLMService(llm=llm, registry=registry, name="llm")

            self._services["llm_service"] = service
            logger.info("LLM service created successfully")
            return service

        except Exception as e:
            logger.error(f"Failed to create LLM service: {e}")
            return None

    def _wrap_with_retry(self, client, client_type: str):
        """Wrap client with retry logic."""
        original_call = client.call

        def call_with_retry(*args, **kwargs):
            last_exception = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    return original_call(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < self.config.max_retries:
                        backoff = self.config.retry_backoff_factor**attempt
                        logger.warning(
                            f"{client_type} call failed (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                            f"retrying in {backoff}s: {e}"
                        )
                        time.sleep(backoff)
                    else:
                        logger.error(
                            f"{client_type} call failed after {self.config.max_retries + 1} attempts"
                        )

            raise last_exception

        client.call = call_with_retry
        return client

    def _wrap_with_circuit_breaker(self, client, client_type: str):
        """Wrap client with circuit breaker."""
        breaker_key = f"{client_type}_breaker"
        self._circuit_breakers[breaker_key] = {
            "failures": 0,
            "state": "closed",  # closed, open, half_open
            "opened_at": None,
        }

        original_call = client.call

        def call_with_circuit_breaker(*args, **kwargs):
            breaker = self._circuit_breakers[breaker_key]

            # Check if circuit is open
            if breaker["state"] == "open":
                if (
                    time.time() - breaker["opened_at"]
                    > self.config.circuit_breaker_timeout
                ):
                    logger.info(f"{client_type} circuit breaker entering half-open state")
                    breaker["state"] = "half_open"
                else:
                    raise RuntimeError(f"{client_type} circuit breaker is open")

            try:
                result = original_call(*args, **kwargs)

                # Reset on success
                if breaker["state"] == "half_open":
                    logger.info(f"{client_type} circuit breaker closing")
                    breaker["state"] = "closed"
                breaker["failures"] = 0

                return result

            except Exception as e:
                breaker["failures"] += 1

                # Open circuit if threshold reached
                if breaker["failures"] >= self.config.circuit_breaker_threshold:
                    if breaker["state"] != "open":
                        logger.warning(
                            f"{client_type} circuit breaker opening after {breaker['failures']} failures"
                        )
                        breaker["state"] = "open"
                        breaker["opened_at"] = time.time()

                raise e

        client.call = call_with_circuit_breaker
        return client

    def create_all_services(self) -> Dict[str, Any]:
        """
        Create all MCP services and wire them together.

        This is the main entry point for full MCP system initialization.

        Returns:
            Dictionary of all created services and clients
        """
        logger.info("Creating all MCP services")

        # Create core services in dependency order
        self.create_service_registry()
        self.create_grpc_client()
        self.create_json_rpc_client()
        self.create_knowledge_graph_service()
        self.create_llm_service()

        all_components = {**self._services, **self._clients}
        logger.info(f"All MCP services created: {list(all_components.keys())}")
        return all_components

    def get_service(self, service_name: str):
        """Get a service by name."""
        return self._services.get(service_name)

    def get_client(self, client_name: str):
        """Get a client by name."""
        return self._clients.get(client_name)

    def get_all_services(self) -> Dict[str, Any]:
        """Get all created services."""
        return self._services.copy()

    def get_all_clients(self) -> Dict[str, Any]:
        """Get all created clients."""
        return self._clients.copy()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on MCP services.

        Returns:
            Dictionary with health status of all services
        """
        if not self.config.enable_health_checks:
            return {"health_checks_disabled": True}

        health = {}

        # Check service registry
        registry = self.get_service("service_registry")
        if registry:
            try:
                services = registry.list()
                health["service_registry"] = {
                    "healthy": True,
                    "service_count": len(services),
                    "services": list(services.keys()),
                }
            except Exception as e:
                health["service_registry"] = {"healthy": False, "error": str(e)}

        # Check clients
        for client_name in ["grpc_client", "json_rpc_client"]:
            client = self.get_client(client_name)
            if client:
                health[client_name] = {"exists": True, "configured": True}

        # Check service wrappers
        for service_name in ["knowledge_graph_service", "llm_service"]:
            service = self.get_service(service_name)
            if service:
                health[service_name] = {"exists": True, "registered": True}

        # Check circuit breakers
        if self.config.enable_circuit_breaker:
            health["circuit_breakers"] = {}
            for breaker_key, breaker in self._circuit_breakers.items():
                health["circuit_breakers"][breaker_key] = {
                    "state": breaker["state"],
                    "failures": breaker["failures"],
                }

        return health

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get metrics from MCP services.

        Returns:
            Dictionary with metrics from all services
        """
        if not self.config.enable_metrics:
            return {"metrics_disabled": True}

        metrics = {
            "services_count": len(self._services),
            "clients_count": len(self._clients),
            "circuit_breakers": {},
        }

        # Circuit breaker metrics
        for breaker_key, breaker in self._circuit_breakers.items():
            metrics["circuit_breakers"][breaker_key] = {
                "state": breaker["state"],
                "failures": breaker["failures"],
                "opened_at": breaker["opened_at"],
            }

        return metrics


# Global factory instance
_global_factory: Optional[MCPServiceFactory] = None


def get_mcp_service_factory(
    config: Optional[MCPServiceConfig] = None,
) -> MCPServiceFactory:
    """
    Get or create global MCP service factory.

    Args:
        config: Optional configuration for the factory

    Returns:
        MCPServiceFactory instance
    """
    global _global_factory

    if _global_factory is None:
        _global_factory = MCPServiceFactory(config)
        logger.info("Global MCP service factory created")

    return _global_factory


def get_service_registry():
    """Get or create global service registry."""
    factory = get_mcp_service_factory()
    registry = factory.get_service("service_registry")

    if registry is None:
        registry = factory.create_service_registry()

    return registry


def get_grpc_client():
    """Get or create global gRPC client."""
    factory = get_mcp_service_factory()
    client = factory.get_client("grpc_client")

    if client is None:
        client = factory.create_grpc_client()

    return client


def get_json_rpc_client():
    """Get or create global JSON-RPC client."""
    factory = get_mcp_service_factory()
    client = factory.get_client("json_rpc_client")

    if client is None:
        client = factory.create_json_rpc_client()

    return client


def get_knowledge_graph_service():
    """Get or create global knowledge graph service."""
    factory = get_mcp_service_factory()
    service = factory.get_service("knowledge_graph_service")

    if service is None:
        service = factory.create_knowledge_graph_service()

    return service


def get_llm_service():
    """Get or create global LLM service."""
    factory = get_mcp_service_factory()
    service = factory.get_service("llm_service")

    if service is None:
        service = factory.create_llm_service()

    return service


def initialize_mcp_for_production():
    """
    Initialize MCP for production use.

    This is the main entry point for production MCP initialization.
    Call this during application startup.
    """
    factory = get_mcp_service_factory()
    factory.create_all_services()
    logger.info("MCP system initialized for production")
    return factory.health_check()


__all__ = [
    "MCPServiceConfig",
    "MCPServiceFactory",
    "get_mcp_service_factory",
    "get_service_registry",
    "get_grpc_client",
    "get_json_rpc_client",
    "get_knowledge_graph_service",
    "get_llm_service",
    "initialize_mcp_for_production",
]
