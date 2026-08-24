import logging
from typing import Dict, Any, Optional, List, AsyncGenerator
from .contracts.runtime_request import RuntimeRequest
from .contracts.runtime_response import RuntimeResponse, ResponseStatus
from .coordinator.medusa_coordinator import MedusaCoordinator
from .registry import get_medusa_registry
from .catalog import AgentCatalogService, AgentDescriptor
from .contracts.safe_error import to_safe_response
from .telemetry.metrics import get_medusa_metrics
from .telemetry.tracing import get_medusa_tracer
from .safety import get_safety_manager
from .adapters.auth_context_adapter import AuthContextAdapter

logger = logging.getLogger(__name__)

class AgentMedusaService:
    """Canonical AgentMedusa Service for agent arbitration and execution."""
    
    def __init__(self, coordinator: Optional[MedusaCoordinator] = None):
        self.coordinator = coordinator or MedusaCoordinator()
        self.registry = get_medusa_registry()
        self.metrics = get_medusa_metrics()
        self.tracer = get_medusa_tracer()
        self.safety = get_safety_manager()
        self.auth = AuthContextAdapter()
        self.catalog = AgentCatalogService(self.registry)
        self._initialized = False

    async def initialize(self):
        """Initialize all Medusa components."""
        if self._initialized:
            return
        
        await self.registry.initialize()
        # Additional initialization logic if needed
        self._initialized = True
        logger.info("AgentMedusaService initialized")

    async def list_agent_catalog(
        self,
        *,
        tenant_visible_ids: Optional[Any] = None,
        rbac_visible_ids: Optional[Any] = None,
        policy_eligible_ids: Optional[Any] = None,
        include_disabled: bool = False,
        capability_health: Optional[Any] = None,
        admin: bool = False,
    ) -> List["AgentDescriptor"]:
        """Backend-driven, filtered agent catalog for the UI (A19 / A20).

        Intersects registered agents with tenant/RBAC/policy-eligible sets
        supplied by upstream authority. Normal users see usable agents;
        admins see all with diagnostic status.
        """
        if not self._initialized:
            await self.initialize()
        return await self.catalog.list_agents(
            tenant_visible_ids=set(tenant_visible_ids) if tenant_visible_ids else None,
            rbac_visible_ids=set(rbac_visible_ids) if rbac_visible_ids else None,
            policy_eligible_ids=set(policy_eligible_ids) if policy_eligible_ids else None,
            include_disabled=include_disabled,
            capability_health=capability_health,
            admin=admin,
        )

    async def execute(self, request: RuntimeRequest) -> RuntimeResponse:
        """Execute a request through the Medusa agent system."""
        if not self._initialized:
            await self.initialize()
        
        correlation_id = request.request_id
        trace = self.tracer.start_trace(agent_id="medusa_coordinator", correlation_id=correlation_id)
        
        try:
            # 1. Safety Check
            safety_result = await self.safety.validate_input(request.query)
            if not safety_result.is_safe:
                self.tracer.add_event(trace.trace_id, "safety_violation", safety_result.reason)
                return RuntimeResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.ERROR,
                    content=f"Safety violation: {safety_result.reason}"
                )

            # 2. Auth/RBAC Check
            # ...

            # 3. Delegate to Coordinator
            response = await self.coordinator.handle_request(request)
            
            # 4. Record Metrics
            success = response.status == ResponseStatus.SUCCESS
            self.metrics.record_execution("medusa_coordinator", trace.duration_ms or 0, success)
            self.tracer.end_trace(trace.trace_id, success)
            
            return response

        except Exception as e:
            logger.error(f"AgentMedusaService execution error: {e}", exc_info=True)
            self.tracer.add_event(trace.trace_id, "error", str(e))
            self.tracer.end_trace(trace.trace_id, success=False)
            return to_safe_response(e, correlation_id=correlation_id)

    # Compatibility methods for migration
    async def execute_task(self, task: Any, execution_mode: Any = None) -> Any:
        """Compatibility method for old AgentTask execution."""
        import warnings

        warnings.warn(
            "AgentMedusaService.execute_task is deprecated. "
            "Use AgentMedusaService.execute with RuntimeRequest instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from .contracts.runtime_request import RuntimeRequest
        request = RuntimeRequest(
            query=task.description,
            session_id=task.task_id,
            user_id="system",
            context=task.input_data
        )
        medusa_response = await self.execute(request)
        
        # Convert Medusa response back to AgentResponse-like object
        # This is a bit hacky but helps migration
        from ai_karen_engine.agents.models import AgentResponse
        return AgentResponse(
            request_id=task.task_id,
            agent_id=task.agent_id,
            execution_mode=execution_mode,
            response=medusa_response.content,
            processing_time=0.0, # Filled by metrics later if needed
            metadata=medusa_response.metadata
        )

    async def execute_request(self, request: Any) -> Any:
        """Compatibility method for old AgentRequest execution."""
        import warnings

        warnings.warn(
            "AgentMedusaService.execute_request is deprecated. "
            "Use AgentMedusaService.execute with RuntimeRequest instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        runtime_request = RuntimeRequest(
            query=request.message,
            session_id=request.session_id or "unknown",
            user_id=request.user_id or "anonymous",
            context=request.context or {}
        )
        medusa_response = await self.execute(runtime_request)
        
        from ai_karen_engine.agents.models import AgentResponse
        return AgentResponse(
            request_id=request.request_id,
            agent_id=medusa_response.agent_trace[0] if medusa_response.agent_trace else "medusa",
            execution_mode=request.execution_mode,
            response=medusa_response.content,
            processing_time=0.0,
            metadata=medusa_response.metadata
        )

_service: Optional[AgentMedusaService] = None

def get_agent_medusa_service() -> AgentMedusaService:
    global _service
    if _service is None:
        _service = AgentMedusaService()
    return _service
