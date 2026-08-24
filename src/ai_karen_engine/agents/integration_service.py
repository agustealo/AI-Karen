"""
Agent Integration Service

.. deprecated::
    The legacy integration service is deprecated. Multi-agent execution is now
    handled by ``ai_karen_engine.agent_medusa``. Legacy UI modes may still use
    this service via ``agents.adapters.medusa_adapter``.
"""

import asyncio
import logging
import warnings
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

warnings.warn(
    "ai_karen_engine.agents.integration_service is deprecated. "
    "Use ai_karen_engine.agent_medusa instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .models import (
    AgentRequest,
    AgentResponse,
    AgentStreamResponse,
    AgentInfo,
    AgentConfig,
    AgentExecutionMode,
    AgentCapability,
    AgentStatus,
    AgentError,
    StreamChunk,
    AgentMetrics,
)
from .execution_handlers import get_execution_handler
from .lifecycle_manager import get_lifecycle_manager
from .capability_router import get_capability_router
from .auth import AgentAuthManager

try:
    from .agent_registry import AgentRegistry

    HAS_AGENT_REGISTRY = True
except Exception:  # pragma: no cover - optional dependency chain
    AgentRegistry = None
    HAS_AGENT_REGISTRY = False

try:
    from .adapters.medusa_adapter import MedusaAdapter
    HAS_MEDUSA_ADAPTER = True
except Exception:  # pragma: no cover - optional dependency chain
    MedusaAdapter = None
    HAS_MEDUSA_ADAPTER = False

logger = logging.getLogger(__name__)


class AgentIntegrationService:
    """Main integration service for agent operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AgentIntegrationService")
        self._initialized = False
        self._active_requests: Dict[str, AgentRequest] = {}
        self._active_streams: Dict[str, AsyncGenerator[StreamChunk, None]] = {}
        self._agent_registry: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._auth = AgentAuthManager()

    async def initialize(self):
        """Initialize the integration service."""
        if self._initialized:
            return

        self.logger.info("Initializing Agent Integration Service")
        
        # Initialize lifecycle manager
        lifecycle_manager = get_lifecycle_manager()
        await lifecycle_manager.initialize()

        # Initialize the persistent registry when available.
        await self._ensure_agent_registry()
        self._initialized = True
        
        self.logger.info("Agent Integration Service initialized")
    
    async def shutdown(self):
        """Shutdown the integration service."""
        self.logger.info("Shutting down Agent Integration Service")
        
        # Cancel all active streams
        async with self._lock:
            for request_id, stream in self._active_streams.items():
                try:
                    if hasattr(stream, 'aclose'):
                        await stream.aclose()
                except Exception as e:
                    self.logger.error(f"Error closing stream for request {request_id}: {e}")
            
            self._active_streams.clear()
            self._active_requests.clear()
        
        # Shutdown lifecycle manager
        lifecycle_manager = get_lifecycle_manager()
        await lifecycle_manager.shutdown()

        # Best-effort registry shutdown if the registry was initialized.
        if self._agent_registry and hasattr(self._agent_registry, "stop"):
            try:
                await self._agent_registry.stop()
            except Exception as e:
                self.logger.error(f"Error stopping agent registry: {e}")

        self._agent_registry = None
        self._initialized = False
        
        self.logger.info("Agent Integration Service shutdown complete")

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    async def _ensure_agent_registry(self) -> Optional[Any]:
        if self._agent_registry is not None:
            return self._agent_registry

        if not HAS_AGENT_REGISTRY or AgentRegistry is None:
            return None

        try:
            self._agent_registry = AgentRegistry()
            await self._agent_registry.initialize()
            await self._sync_registry_agents_to_lifecycle()
        except Exception as e:
            self.logger.warning(f"Agent registry unavailable: {e}")
            self._agent_registry = None

        return self._agent_registry

    async def _sync_registry_agents_to_lifecycle(self) -> None:
        """Mirror persistent registry agents into the runtime lifecycle manager."""
        registry = self._agent_registry
        if registry is None or not hasattr(registry, "list_agents"):
            return

        lifecycle_manager = get_lifecycle_manager()
        try:
            registry_agents = await registry.list_agents()
        except Exception as e:
            self.logger.warning(f"Failed to list registry agents for sync: {e}")
            return

        for agent_data in registry_agents or []:
            info = self._registry_agent_to_info(agent_data)
            if info is None:
                continue

            try:
                existing = await lifecycle_manager.get_agent(info.agent_id)
                if existing is None:
                    await lifecycle_manager.create_agent(
                        agent_id=info.agent_id,
                        name=info.name,
                        description=info.description,
                        execution_mode=info.execution_mode,
                        config=info.config,
                    )
                if info.status != AgentStatus.IDLE:
                    await lifecycle_manager.update_agent_status(
                        info.agent_id,
                        info.status,
                        metadata={"source": "registry_sync"},
                    )
            except Exception as e:
                self.logger.warning(
                    f"Failed to sync registry agent {info.agent_id} to lifecycle manager: {e}"
                )

    @staticmethod
    def _normalize_execution_mode(value: Any) -> AgentExecutionMode:
        if isinstance(value, AgentExecutionMode):
            return value
        if isinstance(value, str):
            try:
                return AgentExecutionMode(value)
            except ValueError:
                pass
        return AgentExecutionMode.NATIVE

    @staticmethod
    def _normalize_status(value: Any) -> AgentStatus:
        if isinstance(value, AgentStatus):
            return value
        if isinstance(value, str):
            normalized = value.lower()
            mapping = {
                "ready": AgentStatus.IDLE,
                "idle": AgentStatus.IDLE,
                "running": AgentStatus.PROCESSING,
                "busy": AgentStatus.PROCESSING,
                "processing": AgentStatus.PROCESSING,
                "streaming": AgentStatus.STREAMING,
                "stopped": AgentStatus.TERMINATED,
                "stopping": AgentStatus.TERMINATED,
                "terminated": AgentStatus.TERMINATED,
                "error": AgentStatus.ERROR,
                "initializing": AgentStatus.INITIALIZING,
            }
            return mapping.get(normalized, AgentStatus.IDLE)
        return AgentStatus.IDLE

    @staticmethod
    def _coerce_capability(value: Any) -> Optional[AgentCapability]:
        if isinstance(value, AgentCapability):
            return value
        if isinstance(value, dict):
            value = value.get("name")
        if isinstance(value, str):
            try:
                return AgentCapability(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _build_agent_config(
        execution_mode: AgentExecutionMode,
        payload: Optional[Dict[str, Any]],
    ) -> AgentConfig:
        data = dict(payload or {})
        capabilities_payload = data.pop("capabilities", [])
        custom_config = dict(data.pop("custom_config", {}) or {})
        data.pop("execution_mode", None)

        capabilities: List[AgentCapability] = []
        for capability in capabilities_payload or []:
            normalized = AgentIntegrationService._coerce_capability(capability)
            if normalized is not None:
                capabilities.append(normalized)

        return AgentConfig(
            execution_mode=execution_mode,
            model_name=data.pop("model_name", None),
            provider=data.pop("provider", None),
            temperature=data.pop("temperature", 0.7),
            max_tokens=data.pop("max_tokens", 2048),
            timeout_seconds=data.pop("timeout_seconds", 60),
            enable_streaming=bool(data.pop("enable_streaming", False)),
            capabilities=capabilities,
            custom_config={**data, **custom_config},
        )

    def _registry_agent_to_info(self, agent_data: Dict[str, Any]) -> Optional[AgentInfo]:
        agent_id = agent_data.get("agent_id") or agent_data.get("id")
        name = agent_data.get("name") or agent_id
        if not agent_id or not name:
            return None

        execution_mode = self._normalize_execution_mode(
            agent_data.get("execution_mode")
            or agent_data.get("agent_type")
            or agent_data.get("metadata", {}).get("execution_mode")
        )
        status = self._normalize_status(agent_data.get("status"))

        capabilities: List[AgentCapability] = []
        for capability in agent_data.get("capabilities", []):
            normalized = self._coerce_capability(capability)
            if normalized is not None:
                capabilities.append(normalized)

        metadata = dict(agent_data.get("metadata") or {})
        config_payload = dict(agent_data.get("config") or {})
        custom_config = dict(metadata.get("config") or config_payload)

        config = AgentConfig(
            execution_mode=execution_mode,
            model_name=metadata.get("model_name"),
            provider=metadata.get("provider"),
            capabilities=capabilities,
            custom_config=custom_config,
        )

        metrics = AgentMetrics(
            agent_id=agent_id,
            execution_mode=execution_mode,
        )

        performance = agent_data.get("performance") or {}
        response_time = performance.get("response_time") or {}
        if isinstance(response_time, dict):
            metrics.average_response_time = float(response_time.get("avg", 0.0) or 0.0)
            metrics.total_requests = int(response_time.get("count", 0) or 0)
            metrics.successful_requests = int(
                round(metrics.total_requests * float(performance.get("success_rate", {}).get("avg", 0.0) or 0.0))
            )
            metrics.failed_requests = max(
                0, metrics.total_requests - metrics.successful_requests
            )

        created_at = agent_data.get("registered_at") or agent_data.get("created_at")
        last_activity = agent_data.get("updated_at") or agent_data.get("last_activity")

        def _parse_dt(value: Any) -> datetime:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except Exception:
                    pass
            return datetime.utcnow()

        return AgentInfo(
            agent_id=agent_id,
            name=name,
            description=agent_data.get("description") or "",
            execution_mode=execution_mode,
            status=status,
            capabilities=capabilities,
            config=config,
            metrics=metrics,
            created_at=_parse_dt(created_at),
            last_activity=_parse_dt(last_activity) if last_activity else None,
            version=agent_data.get("version") or "1.0.0",
        )

    async def _merge_agent_sources(self) -> List[AgentInfo]:
        lifecycle_manager = get_lifecycle_manager()
        lifecycle_agents = await lifecycle_manager.get_all_agents()
        merged: Dict[str, AgentInfo] = {agent.agent_id: agent for agent in lifecycle_agents}

        registry = await self._ensure_agent_registry()
        if registry is not None and hasattr(registry, "list_agents"):
            try:
                registry_agents = await registry.list_agents()
                for agent_data in registry_agents or []:
                    info = self._registry_agent_to_info(agent_data)
                    if info is not None and info.agent_id not in merged:
                        merged[info.agent_id] = info
            except Exception as e:
                self.logger.warning(f"Failed to read registry agents: {e}")

        return list(merged.values())
    
    async def execute_request(self, request: AgentRequest) -> AgentResponse:
        """
        Execute an agent request synchronously.
        
        Args:
            request: The agent request to execute
            
        Returns:
            Agent response
        """
        await self._ensure_initialized()

        self.logger.info(
            f"Executing request {request.request_id} in {request.execution_mode.value} mode"
        )
        
        start_time = datetime.utcnow()
        
        try:
            # Track active request
            async with self._lock:
                self._active_requests[request.request_id] = request
            
            # Validate request feasibility
            router = get_capability_router()
            is_feasible, issues = await router.validate_request_feasibility(request)
            
            if not is_feasible:
                return AgentResponse(
                    request_id=request.request_id,
                    agent_id="none",
                    execution_mode=request.execution_mode,
                    response="",
                    processing_time=0.0,
                    error=AgentError(
                        code="REQUEST_NOT_FEASIBLE",
                        message="Request cannot be fulfilled with available agents",
                        details={"issues": issues},
                        recoverable=False
                    )
                )
            
            # Route request to appropriate agent
            selected_agent, routing_metadata = await router.route_request(request)
            
            if not selected_agent:
                return AgentResponse(
                    request_id=request.request_id,
                    agent_id="none",
                    execution_mode=request.execution_mode,
                    response="",
                    processing_time=0.0,
                    error=AgentError(
                        code="NO_SUITABLE_AGENT",
                        message="No suitable agent found for request",
                        details=routing_metadata,
                        recoverable=True
                    )
                )
            
            # Update agent status to processing
            lifecycle_manager = get_lifecycle_manager()
            await lifecycle_manager.update_agent_status(
                selected_agent.agent_id,
                AgentStatus.PROCESSING,
                metadata={"request_id": request.request_id}
            )
            
            # Get execution handler or delegate to Medusa for multi-agent
            if selected_agent.execution_mode == AgentExecutionMode.DEEP_AGENTS and HAS_MEDUSA_ADAPTER:
                medusa_adapter = MedusaAdapter()
                response = await medusa_adapter.execute(request)
                response.metadata.update({
                    "routing": routing_metadata,
                    "selected_agent": {
                        "agent_id": selected_agent.agent_id,
                        "name": selected_agent.name,
                        "execution_mode": selected_agent.execution_mode.value,
                        "delegated_to": "medusa",
                    }
                })
                return response
            
            handler = get_execution_handler(selected_agent.execution_mode)
            
            # Update request with selected agent info
            request.agent_id = selected_agent.agent_id
            
            # Execute request
            response = await handler.execute(request)
            
            # Update response metadata with routing information
            response.metadata.update({
                "routing": routing_metadata,
                "selected_agent": {
                    "agent_id": selected_agent.agent_id,
                    "name": selected_agent.name,
                    "execution_mode": selected_agent.execution_mode.value
                }
            })
            
            # Update agent metrics
            await self._update_agent_metrics(selected_agent.agent_id, response, start_time)
            
            # Update agent status back to idle
            await lifecycle_manager.update_agent_status(
                selected_agent.agent_id,
                AgentStatus.IDLE
            )
            
            self.logger.info(f"Request {request.request_id} completed successfully")
            return response
            
        except Exception as e:
            self.logger.error(f"Error executing request {request.request_id}: {e}")
            
            # Update agent status to error if we have one
            if 'selected_agent' in locals():
                await lifecycle_manager.update_agent_status(
                    selected_agent.agent_id,
                    AgentStatus.ERROR,
                    metadata={"error": str(e)}
                )
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "unknown",
                execution_mode=request.execution_mode,
                response="",
                processing_time=processing_time,
                error=AgentError(
                    code="EXECUTION_ERROR",
                    message=str(e),
                    recoverable=True
                )
            )
        
        finally:
            # Clean up active request
            async with self._lock:
                self._active_requests.pop(request.request_id, None)
    
    async def execute_request_stream(self, request: AgentRequest) -> AsyncGenerator[AgentStreamResponse, None]:
        """
        Execute an agent request with streaming response.
        
        Args:
            request: The agent request to execute
            
        Yields:
            Agent stream responses
        """
        await self._ensure_initialized()

        self.logger.info(
            f"Starting stream for request {request.request_id} in {request.execution_mode.value} mode"
        )
        
        try:
            # Track active request and stream
            async with self._lock:
                self._active_requests[request.request_id] = request
            
            # Validate request feasibility
            router = get_capability_router()
            is_feasible, issues = await router.validate_request_feasibility(request)
            
            if not is_feasible:
                yield AgentStreamResponse(
                    request_id=request.request_id,
                    agent_id="none",
                    execution_mode=request.execution_mode,
                    chunk=StreamChunk(
                        content="Request cannot be fulfilled with available agents",
                        chunk_type="error",
                        is_final=True
                    ),
                    is_complete=True,
                    error=AgentError(
                        code="REQUEST_NOT_FEASIBLE",
                        message="Request cannot be fulfilled with available agents",
                        details={"issues": issues},
                        recoverable=False
                    )
                )
                return
            
            # Route request to appropriate agent
            selected_agent, routing_metadata = await router.route_request(request)
            
            if not selected_agent:
                yield AgentStreamResponse(
                    request_id=request.request_id,
                    agent_id="none",
                    execution_mode=request.execution_mode,
                    chunk=StreamChunk(
                        content="No suitable agent found for request",
                        chunk_type="error",
                        is_final=True
                    ),
                    is_complete=True,
                    error=AgentError(
                        code="NO_SUITABLE_AGENT",
                        message="No suitable agent found for request",
                        details=routing_metadata,
                        recoverable=True
                    )
                )
                return
            
            # Update agent status to streaming
            lifecycle_manager = get_lifecycle_manager()
            await lifecycle_manager.update_agent_status(
                selected_agent.agent_id,
                AgentStatus.STREAMING,
                metadata={"request_id": request.request_id}
            )
            
            # Get execution handler or delegate to Medusa for multi-agent
            if selected_agent.execution_mode == AgentExecutionMode.DEEP_AGENTS and HAS_MEDUSA_ADAPTER:
                medusa_adapter = MedusaAdapter()
                async for stream_response in medusa_adapter.execute_stream(request):
                    stream_response.metadata = stream_response.metadata or {}
                    stream_response.metadata.update({
                        "routing": routing_metadata,
                        "selected_agent": {
                            "agent_id": selected_agent.agent_id,
                            "name": selected_agent.name,
                            "execution_mode": selected_agent.execution_mode.value,
                            "delegated_to": "medusa",
                        }
                    })
                    yield stream_response
                return
            
            handler = get_execution_handler(selected_agent.execution_mode)
            
            # Update request with selected agent info
            request.agent_id = selected_agent.agent_id
            
            # Start streaming
            full_response = ""
            chunk_count = 0
            
            async for chunk in handler.execute_stream(request):
                chunk_count += 1
                
                # Accumulate response text
                if chunk.chunk_type == "text":
                    full_response += chunk.content
                
                # Create stream response
                stream_response = AgentStreamResponse(
                    request_id=request.request_id,
                    agent_id=selected_agent.agent_id,
                    execution_mode=selected_agent.execution_mode,
                    chunk=chunk,
                    metadata={
                        "routing": routing_metadata,
                        "selected_agent": {
                            "agent_id": selected_agent.agent_id,
                            "name": selected_agent.name,
                            "execution_mode": selected_agent.execution_mode.value
                        },
                        "chunk_count": chunk_count
                    },
                    is_complete=chunk.is_final
                )
                
                yield stream_response
                
                # Check if streaming is complete
                if chunk.is_final:
                    break
            
            # Update agent metrics
            await self._update_agent_metrics(selected_agent.agent_id, None, datetime.utcnow(), full_response)
            
            # Update agent status back to idle
            await lifecycle_manager.update_agent_status(
                selected_agent.agent_id,
                AgentStatus.IDLE
            )
            
            self.logger.info(f"Stream for request {request.request_id} completed successfully")
            
        except Exception as e:
            self.logger.error(f"Error in stream for request {request.request_id}: {e}")
            
            # Update agent status to error if we have one
            if 'selected_agent' in locals():
                await lifecycle_manager.update_agent_status(
                    selected_agent.agent_id,
                    AgentStatus.ERROR,
                    metadata={"error": str(e)}
                )
            
            yield AgentStreamResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "unknown",
                execution_mode=request.execution_mode,
                chunk=StreamChunk(
                    content=f"Streaming error: {str(e)}",
                    chunk_type="error",
                    is_final=True
                ),
                is_complete=True,
                error=AgentError(
                    code="STREAMING_ERROR",
                    message=str(e),
                    recoverable=True
                )
            )
        
        finally:
            # Clean up active request
            async with self._lock:
                self._active_requests.pop(request.request_id, None)
                self._active_streams.pop(request.request_id, None)
    
    async def get_agent_info(self, agent_id: str) -> Optional[AgentInfo]:
        """Get information about a specific agent."""
        await self._ensure_initialized()

        lifecycle_manager = get_lifecycle_manager()
        agent = await lifecycle_manager.get_agent(agent_id)
        if agent:
            return agent

        registry = await self._ensure_agent_registry()
        if registry is None or not hasattr(registry, "get_agent"):
            return None

        try:
            agent_data = await registry.get_agent(agent_id)
            return self._registry_agent_to_info(agent_data) if agent_data else None
        except Exception as e:
            self.logger.warning(f"Registry lookup failed for agent {agent_id}: {e}")
            return None
    
    async def get_all_agents(self) -> List[AgentInfo]:
        """Get information about all agents."""
        await self._ensure_initialized()
        return await self._merge_agent_sources()
    
    async def get_agents_by_execution_mode(self, execution_mode: AgentExecutionMode) -> List[AgentInfo]:
        """Get agents by execution mode."""
        await self._ensure_initialized()
        agents = await self._merge_agent_sources()
        return [agent for agent in agents if agent.execution_mode == execution_mode]
    
    async def get_available_agents(
        self,
        execution_mode: Optional[AgentExecutionMode] = None,
        capabilities: Optional[List[AgentCapability]] = None
    ) -> List[AgentInfo]:
        """Get available agents that match criteria."""
        await self._ensure_initialized()
        lifecycle_manager = get_lifecycle_manager()
        lifecycle_agents = await lifecycle_manager.get_available_agents(
            execution_mode, capabilities
        )

        agents = {agent.agent_id: agent for agent in lifecycle_agents}
        for agent in await self._merge_agent_sources():
            if agent.agent_id in agents:
                continue
            if execution_mode and agent.execution_mode != execution_mode:
                continue
            if capabilities and not all(cap in agent.capabilities for cap in capabilities):
                continue
            if agent.is_available:
                agents[agent.agent_id] = agent

        return list(agents.values())
    
    async def create_agent(
        self,
        agent_id: str,
        name: str,
        description: str,
        execution_mode: AgentExecutionMode,
        config: Dict[str, Any]
    ) -> AgentInfo:
        """Create a new agent."""
        await self._ensure_initialized()

        # Convert config dict to AgentConfig using the explicit execution mode.
        agent_config = self._build_agent_config(execution_mode, config)
        
        lifecycle_manager = get_lifecycle_manager()
        created_agent = await lifecycle_manager.create_agent(
            agent_id=agent_id,
            name=name,
            description=description,
            execution_mode=execution_mode,
            config=agent_config
        )

        registry = await self._ensure_agent_registry()
        if registry is not None and hasattr(registry, "register_agent"):
            try:
                await registry.register_agent(
                    agent_id=agent_id,
                    agent_type=execution_mode.value,
                    capabilities=[cap.value for cap in agent_config.capabilities],
                    metadata={
                        "name": name,
                        "description": description,
                        "execution_mode": execution_mode.value,
                        "config": config,
                    },
                    version=created_agent.version,
                )
            except Exception as e:
                self.logger.warning(f"Failed to register agent {agent_id} in registry: {e}")

        return created_agent
    
    async def terminate_agent(self, agent_id: str) -> bool:
        """Terminate an agent."""
        await self._ensure_initialized()

        lifecycle_manager = get_lifecycle_manager()
        success = await lifecycle_manager.terminate_agent(agent_id)

        registry = await self._ensure_agent_registry()
        if registry is not None and hasattr(registry, "update_agent_status"):
            try:
                await registry.update_agent_status(agent_id, "stopped")
            except Exception as e:
                self.logger.warning(f"Failed to update registry status for {agent_id}: {e}")

        return success
    
    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent."""
        await self._ensure_initialized()

        lifecycle_manager = get_lifecycle_manager()
        success = await lifecycle_manager.delete_agent(agent_id)

        registry = await self._ensure_agent_registry()
        if registry is not None and hasattr(registry, "unregister_agent"):
            try:
                await registry.unregister_agent(agent_id)
            except Exception as e:
                self.logger.warning(f"Failed to unregister agent {agent_id} from registry: {e}")

        return success
    
    async def get_agent_metrics(self, agent_id: str) -> Optional[AgentMetrics]:
        """Get metrics for a specific agent."""
        await self._ensure_initialized()

        agent_info = await self.get_agent_info(agent_id)
        if agent_info:
            return agent_info.metrics

        registry = await self._ensure_agent_registry()
        if registry is None or not hasattr(registry, "get_agent"):
            return None

        try:
            agent_data = await registry.get_agent(agent_id)
            info = self._registry_agent_to_info(agent_data) if agent_data else None
            return info.metrics if info else None
        except Exception as e:
            self.logger.warning(f"Registry metrics lookup failed for agent {agent_id}: {e}")
            return None

    async def get_agent_lifecycle_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get lifecycle events for the agent management surface."""
        await self._ensure_initialized()
        lifecycle_manager = get_lifecycle_manager()
        events = await lifecycle_manager.get_lifecycle_events(
            agent_id=agent_id, event_type=event_type, limit=limit
        )
        return [
            event.dict() if hasattr(event, "dict") else dict(event)
            for event in events
        ]
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get system-wide metrics."""
        await self._ensure_initialized()

        agents = await self._merge_agent_sources()
        
        total_requests = sum(agent.metrics.total_requests for agent in agents)
        total_successful = sum(agent.metrics.successful_requests for agent in agents)
        total_failed = sum(agent.metrics.failed_requests for agent in agents)
        
        # Count agents by status
        status_counts = {}
        for status in AgentStatus:
            status_counts[status.value] = sum(1 for agent in agents if agent.status == status)
        
        # Count agents by execution mode
        mode_counts = {}
        for mode in AgentExecutionMode:
            mode_counts[mode.value] = sum(1 for agent in agents if agent.execution_mode == mode)
        
        return {
            "total_agents": len(agents),
            "total_requests": total_requests,
            "successful_requests": total_successful,
            "failed_requests": total_failed,
            "overall_success_rate": total_successful / total_requests if total_requests > 0 else 0.0,
            "agents_by_status": status_counts,
            "agents_by_execution_mode": mode_counts,
            "active_requests": len(self._active_requests),
            "active_streams": len(self._active_streams),
            "registry_enabled": self._agent_registry is not None,
        }
    
    async def cancel_request(self, request_id: str) -> bool:
        """Cancel an active request."""
        await self._ensure_initialized()

        async with self._lock:
            if request_id in self._active_requests:
                # Cancel the stream if it exists
                if request_id in self._active_streams:
                    try:
                        stream = self._active_streams[request_id]
                        if hasattr(stream, 'aclose'):
                            await stream.aclose()
                    except Exception as e:
                        self.logger.error(f"Error canceling stream for request {request_id}: {e}")
                    finally:
                        self._active_streams.pop(request_id, None)
                
                # Remove from active requests
                self._active_requests.pop(request_id, None)
                
                self.logger.info(f"Cancelled request {request_id}")
                return True
            
            return False
    
    async def _update_agent_metrics(
        self,
        agent_id: str,
        response: Optional[AgentResponse],
        start_time: datetime,
        full_response_text: Optional[str] = None
    ):
        """Update agent metrics after request completion."""
        try:
            await self._ensure_initialized()

            lifecycle_manager = get_lifecycle_manager()
            
            # Get current metrics
            agent_info = await lifecycle_manager.get_agent(agent_id)
            if not agent_info:
                return
            
            metrics_update = {
                "total_requests": agent_info.metrics.total_requests + 1,
                "last_request_time": datetime.utcnow()
            }
            
            # Update success/failure counts
            if response:
                if response.error:
                    metrics_update["failed_requests"] = agent_info.metrics.failed_requests + 1
                else:
                    metrics_update["successful_requests"] = agent_info.metrics.successful_requests + 1
                
                # Update average response time
                total_time = agent_info.metrics.average_response_time * agent_info.metrics.total_requests
                new_total_time = total_time + response.processing_time
                metrics_update["average_response_time"] = new_total_time / metrics_update["total_requests"]
            
            # Update metrics
            await lifecycle_manager.update_agent_metrics(agent_id, metrics_update)

            registry = await self._ensure_agent_registry()
            if registry is not None and hasattr(registry, "record_agent_performance"):
                try:
                    await registry.record_agent_performance(
                        agent_id=agent_id,
                        response_time=response.processing_time if response else 0.0,
                        success=not bool(response and response.error),
                        error_type=response.error.code if response and response.error else None,
                        task_type="agent_request",
                        metadata={
                            "request_id": response.request_id if response else agent_id,
                            "source": "integration_service",
                        },
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to record registry performance for {agent_id}: {e}")
            
        except Exception as e:
            self.logger.error(f"Error updating metrics for agent {agent_id}: {e}")


# Global integration service instance
_integration_service: Optional[AgentIntegrationService] = None


def get_agent_integration_service() -> AgentIntegrationService:
    """Get the global agent integration service instance."""
    global _integration_service
    if _integration_service is None:
        _integration_service = AgentIntegrationService()
    return _integration_service


async def initialize_agent_integration():
    """Initialize the global agent integration service."""
    service = get_agent_integration_service()
    await service.initialize()


async def shutdown_agent_integration():
    """Shutdown the global agent integration service."""
    service = get_agent_integration_service()
    await service.shutdown()
