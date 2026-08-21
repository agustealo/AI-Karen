"""
API Routes for Agent Integration System

This module provides REST API endpoints for interacting with the Agent Integration system,
including agent management, request execution, and monitoring.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai_karen_engine.auth.auth_utils import get_current_user
from ai_karen_engine.agents import (
    get_agent_integration_service,
    AgentExecutionMode,
    AgentCapability,
    AgentRequest,
    AgentConfig,
)
from ai_karen_engine.agents.auth import AgentAuthManager, AgentPermission
from ai_karen_engine.agents.lifecycle_manager import get_lifecycle_manager

logger = logging.getLogger(__name__)
_AGENT_AUTH = AgentAuthManager()

router = APIRouter(prefix="/api/agents", tags=["agent-integration"])


async def _get_authenticated_user(request: Request) -> Dict[str, Any]:
    """Prefer the user already resolved by middleware before re-authenticating."""
    if hasattr(request.state, "user") and request.state.user:
        return request.state.user
    return await get_current_user(request)


# Request/Response Models for API
class AgentExecuteRequest(BaseModel):
    """Request model for agent execution."""

    message: str = Field(..., description="Message to send to agent")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode to use")
    agent_id: Optional[str] = Field(None, description="Specific agent ID to use")
    conversation_history: List[Dict[str, Any]] = Field(
        default_factory=list, description="Conversation history"
    )
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    session_id: Optional[str] = Field(None, description="Session ID")
    capabilities_required: List[str] = Field(
        default_factory=list, description="Required capabilities"
    )
    enable_streaming: bool = Field(False, description="Enable streaming response")
    timeout_seconds: Optional[int] = Field(
        None, description="Request timeout in seconds"
    )
    config: Optional[Dict[str, Any]] = Field(None, description="Agent configuration")


class AgentCreateRequest(BaseModel):
    """Request model for creating an agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    config: Dict[str, Any] = Field(..., description="Agent configuration")


class AgentExecuteResponse(BaseModel):
    """Response model for agent execution."""

    request_id: str = Field(..., description="Request identifier")
    agent_id: str = Field(..., description="Agent ID that processed the request")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode used")
    response: str = Field(..., description="Agent response")
    processing_time: float = Field(..., description="Processing time in seconds")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Response metadata"
    )
    confidence: Optional[float] = Field(None, description="Response confidence")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    error: Optional[Dict[str, Any]] = Field(
        None, description="Error information if failed"
    )


class AgentInfoResponse(BaseModel):
    """Response model for agent information."""

    agent_id: str = Field(..., description="Agent identifier")
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    status: str = Field(..., description="Current status")
    capabilities: List[str] = Field(..., description="Available capabilities")
    config: Dict[str, Any] = Field(..., description="Agent configuration")
    metrics: Dict[str, Any] = Field(..., description="Performance metrics")
    created_at: str = Field(..., description="Creation timestamp")
    last_activity: Optional[str] = Field(None, description="Last activity timestamp")
    version: str = Field(..., description="Agent version")
    is_healthy: bool = Field(..., description="Whether agent is healthy")
    is_available: bool = Field(..., description="Whether agent is available")


# Helper functions
def _convert_agent_info_to_response(agent_info) -> AgentInfoResponse:
    """Convert AgentInfo to API response format."""
    return AgentInfoResponse(
        agent_id=agent_info.agent_id,
        name=agent_info.name,
        description=agent_info.description,
        execution_mode=agent_info.execution_mode,
        status=agent_info.status.value,
        capabilities=[cap.value for cap in agent_info.capabilities],
        config=agent_info.config.dict(),
        metrics=agent_info.metrics.dict(),
        created_at=agent_info.created_at.isoformat(),
        last_activity=agent_info.last_activity.isoformat()
        if agent_info.last_activity
        else None,
        version=agent_info.version,
        is_healthy=agent_info.is_healthy,
        is_available=agent_info.is_available,
    )


def _convert_agent_response_to_api_response(response) -> AgentExecuteResponse:
    """Convert AgentResponse to API response format."""
    return AgentExecuteResponse(
        request_id=response.request_id,
        agent_id=response.agent_id,
        execution_mode=response.execution_mode,
        response=response.response,
        processing_time=response.processing_time,
        metadata=response.metadata,
        confidence=response.confidence,
        warnings=response.warnings,
        error=response.error.dict() if response.error else None,
    )


def _user_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    if hasattr(user, "to_dict"):
        return user.to_dict()
    return dict(user or {})


def _has_agent_permission(user: Dict[str, Any], permission: str) -> bool:
    return _AGENT_AUTH.has_permission(_user_payload(user), permission)


async def _get_live_agents_from_runtime() -> List[Any]:
    """Fallback path that reads the live lifecycle manager directly."""
    lifecycle_manager = get_lifecycle_manager()
    try:
        return await lifecycle_manager.get_all_agents()
    except Exception as e:
        logger.warning(f"Lifecycle manager agent lookup failed: {e}")
        return []



# API Endpoints
@router.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(
    http_request: Request,
    request: AgentExecuteRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Execute a request through the agent integration system.

    Args:
        request: Execution request
        background_tasks: FastAPI background tasks
        current_user: Current authenticated user

    Returns:
        Agent execution response
    """
    try:
        # Get integration service
        integration_service = get_agent_integration_service()

        # Convert capabilities from strings to enum
        capabilities = []
        for cap_str in request.capabilities_required:
            try:
                capabilities.append(AgentCapability(cap_str))
            except ValueError:
                logger.warning(f"Unknown capability: {cap_str}")

        # Create agent request
        agent_request = AgentRequest(
            message=request.message,
            execution_mode=request.execution_mode,
            agent_id=request.agent_id,
            conversation_history=request.conversation_history,
            context=request.context,
            user_id=current_user.get("id") or current_user.get("user_id"),
            session_id=request.session_id,
            capabilities_required=capabilities,
            enable_streaming=request.enable_streaming,
            timeout_seconds=request.timeout_seconds,
            config=integration_service._build_agent_config(
                request.execution_mode, request.config
            )
            if request.config
            else None,
        )

        if not _AGENT_AUTH.can_execute_request(_user_payload(current_user), agent_request):
            raise HTTPException(status_code=403, detail="Agent execution permission denied")

        # Execute request
        response = await integration_service.execute_request(agent_request)

        # Convert to API response format
        return _convert_agent_response_to_api_response(response)

    except Exception as e:
        logger.error(f"Agent execution error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent execution error: {str(e)}")


@router.post("/execute/stream")
async def execute_agent_stream(
    http_request: Request,
    request: AgentExecuteRequest,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Execute a request with streaming response through the agent integration system.

    Args:
        request: Execution request
        current_user: Current authenticated user

    Returns:
        Streaming response
    """
    try:
        # Get integration service
        integration_service = get_agent_integration_service()

        # Convert capabilities from strings to enum
        capabilities = []
        for cap_str in request.capabilities_required:
            try:
                capabilities.append(AgentCapability(cap_str))
            except ValueError:
                logger.warning(f"Unknown capability: {cap_str}")

        # Create agent request
        agent_request = AgentRequest(
            message=request.message,
            execution_mode=request.execution_mode,
            agent_id=request.agent_id,
            conversation_history=request.conversation_history,
            context=request.context,
            user_id=current_user.get("id") or current_user.get("user_id"),
            session_id=request.session_id,
            capabilities_required=capabilities,
            enable_streaming=True,
            timeout_seconds=request.timeout_seconds,
            config=integration_service._build_agent_config(
                request.execution_mode, request.config
            )
            if request.config
            else None,
        )

        if not _AGENT_AUTH.can_execute_request(_user_payload(current_user), agent_request):
            raise HTTPException(status_code=403, detail="Agent execution permission denied")

        async def generate_stream():
            """Generate streaming response."""
            try:
                async for stream_response in integration_service.execute_request_stream(
                    agent_request
                ):
                    # Convert to JSON and send as SSE
                    chunk_data = {
                        "request_id": stream_response.request_id,
                        "agent_id": stream_response.agent_id,
                        "execution_mode": stream_response.execution_mode.value,
                        "chunk": {
                            "chunk_id": stream_response.chunk.chunk_id,
                            "content": stream_response.chunk.content,
                            "chunk_type": stream_response.chunk.chunk_type,
                            "metadata": stream_response.chunk.metadata,
                            "is_final": stream_response.chunk.is_final,
                            "timestamp": stream_response.chunk.timestamp.isoformat(),
                        },
                        "metadata": stream_response.metadata,
                        "is_complete": stream_response.is_complete,
                        "final_response": stream_response.final_response,
                        "error": stream_response.error.dict()
                        if stream_response.error
                        else None,
                    }

                    yield f"data: {json.dumps(chunk_data)}\n\n"

                    # End of stream if complete
                    if stream_response.is_complete:
                        break

                # Send final marker
                yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_chunk = {
                    "type": "error",
                    "content": f"Streaming error: {str(e)}",
                    "timestamp": "now",
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except Exception as e:
        logger.error(f"Agent streaming setup error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Agent streaming setup error: {str(e)}"
        )


@router.get("/", response_model=List[AgentInfoResponse])
async def get_all_agents(
    http_request: Request,
    execution_mode: Optional[AgentExecutionMode] = Query(
        None, description="Filter by execution mode"
    ),
    status: Optional[str] = Query(None, description="Filter by status"),
    capabilities: Optional[List[str]] = Query(
        None, description="Filter by capabilities"
    ),
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Get all agents with optional filtering.

    Args:
        execution_mode: Filter by execution mode
        status: Filter by status
        capabilities: Filter by capabilities
        current_user: Current authenticated user

    Returns:
        List of agent information
    """
    try:
        agents: List[Any] = []
        try:
            integration_service = get_agent_integration_service()
            await integration_service.initialize()

            if execution_mode:
                agents = await integration_service.get_agents_by_execution_mode(
                    execution_mode
                )
            elif capabilities:
                cap_list = [
                    AgentCapability(cap)
                    for cap in capabilities
                    if cap in [c.value for c in AgentCapability]
                ]
                agents = await integration_service.get_available_agents(
                    capabilities=cap_list
                )
            else:
                agents = await integration_service.get_all_agents()
        except Exception as service_error:
            logger.warning(
                f"Agent integration service unavailable for list_agents; falling back to lifecycle data: {service_error}"
            )
            agents = await _get_live_agents_from_runtime()

        if not _has_agent_permission(current_user, AgentPermission.VIEW_AGENT):
            raise HTTPException(status_code=403, detail="View permission required")

        # Filter by status if provided
        if status:
            agents = [agent for agent in agents if agent.status.value == status]

        # Convert to response format
        return [_convert_agent_info_to_response(agent) for agent in agents]

    except Exception as e:
        logger.error(f"Get agents error: {e}")
        raise HTTPException(status_code=500, detail=f"Get agents error: {str(e)}")


@router.get("/{agent_id}", response_model=AgentInfoResponse)
async def get_agent(
    http_request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Get information about a specific agent.

    Args:
        agent_id: Agent identifier
        current_user: Current authenticated user

    Returns:
        Agent information
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.VIEW_AGENT):
            raise HTTPException(status_code=403, detail="View permission required")

        agent = None
        try:
            integration_service = get_agent_integration_service()
            await integration_service.initialize()
            agent = await integration_service.get_agent_info(agent_id)
        except Exception as service_error:
            logger.warning(
                f"Agent integration service unavailable for get_agent; falling back to lifecycle data: {service_error}"
            )
            lifecycle_manager = get_lifecycle_manager()
            agent = await lifecycle_manager.get_agent(agent_id)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Convert to response format
        return _convert_agent_info_to_response(agent)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Get agent error: {str(e)}")


@router.post("/", response_model=AgentInfoResponse)
async def create_agent(
    http_request: Request,
    request: AgentCreateRequest,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Create a new agent.

    Args:
        request: Agent creation request
        current_user: Current authenticated user

    Returns:
        Created agent information
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.CREATE_AGENT):
            raise HTTPException(status_code=403, detail="Create permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Create agent
        agent = await integration_service.create_agent(
            agent_id=request.agent_id,
            name=request.name,
            description=request.description,
            execution_mode=request.execution_mode,
            config=request.config,
        )

        # Convert to response format
        return _convert_agent_info_to_response(agent)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Create agent error: {str(e)}")


@router.delete("/{agent_id}")
async def delete_agent(
    http_request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Delete an agent.

    Args:
        agent_id: Agent identifier
        current_user: Current authenticated user

    Returns:
        Success message
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.DELETE_AGENT):
            raise HTTPException(status_code=403, detail="Delete permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Delete agent
        success = await integration_service.delete_agent(agent_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return {"message": f"Agent {agent_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Delete agent error: {str(e)}")


@router.post("/{agent_id}/terminate")
async def terminate_agent(
    http_request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Terminate an agent.

    Args:
        agent_id: Agent identifier
        current_user: Current authenticated user

    Returns:
        Success message
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.TERMINATE_AGENT):
            raise HTTPException(status_code=403, detail="Terminate permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Terminate agent
        success = await integration_service.terminate_agent(agent_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return {"message": f"Agent {agent_id} terminated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Terminate agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Terminate agent error: {str(e)}")


@router.get("/{agent_id}/events")
async def get_agent_events(
    http_request: Request,
    agent_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum number of events"),
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """Get lifecycle events for a specific agent."""
    try:
        if not _has_agent_permission(current_user, AgentPermission.VIEW_LIFECYCLE_EVENTS):
            raise HTTPException(status_code=403, detail="Lifecycle events permission required")

        integration_service = get_agent_integration_service()
        events = await integration_service.get_agent_lifecycle_events(
            agent_id=agent_id, limit=limit
        )
        return events
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get agent events error: {e}")
        raise HTTPException(status_code=500, detail=f"Get agent events error: {str(e)}")


@router.get("/system/metrics")
async def get_system_metrics(
    http_request: Request,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Get system-wide metrics.

    Args:
        current_user: Current authenticated user

    Returns:
        System metrics
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.VIEW_SYSTEM_METRICS):
            raise HTTPException(status_code=403, detail="System metrics permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Get system metrics
        metrics = await integration_service.get_system_metrics()

        return metrics

    except Exception as e:
        logger.error(f"Get system metrics error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Get system metrics error: {str(e)}"
        )


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    http_request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Get metrics for a specific agent.

    Args:
        agent_id: Agent identifier
        current_user: Current authenticated user

    Returns:
        Agent metrics
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.VIEW_METRICS):
            raise HTTPException(status_code=403, detail="Metrics permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Get agent metrics
        metrics = await integration_service.get_agent_metrics(agent_id)

        if not metrics:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return metrics.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get agent metrics error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Get agent metrics error: {str(e)}"
        )


@router.post("/requests/{request_id}/cancel")
async def cancel_request(
    http_request: Request,
    request_id: str,
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Cancel an active request.

    Args:
        request_id: Request identifier
        current_user: Current authenticated user

    Returns:
        Success message
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.CANCEL_REQUEST):
            raise HTTPException(status_code=403, detail="Cancel request permission required")

        # Get integration service
        integration_service = get_agent_integration_service()

        # Cancel request
        success = await integration_service.cancel_request(request_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Request {request_id} not found or not active"
            )

        return {"message": f"Request {request_id} cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel request error: {e}")
        raise HTTPException(status_code=500, detail=f"Cancel request error: {str(e)}")


@router.get("/routing/recommendations")
async def get_routing_recommendations(
    http_request: Request,
    capabilities: List[str] = Query(..., description="Required capabilities"),
    execution_mode: Optional[AgentExecutionMode] = Query(
        None, description="Preferred execution mode"
    ),
    limit: int = Query(5, ge=1, le=20, description="Maximum number of recommendations"),
    current_user: Dict[str, Any] = Depends(_get_authenticated_user),
):
    """
    Get routing recommendations for given requirements.

    Args:
        capabilities: Required capabilities
        execution_mode: Preferred execution mode
        limit: Maximum number of recommendations
        current_user: Current authenticated user

    Returns:
        Routing recommendations
    """
    try:
        if not _has_agent_permission(current_user, AgentPermission.VIEW_ROUTING_RECOMMENDATIONS):
            raise HTTPException(status_code=403, detail="Routing recommendations permission required")

        # Convert capabilities from strings to enum
        cap_list = []
        for cap_str in capabilities:
            try:
                cap_list.append(AgentCapability(cap_str))
            except ValueError:
                logger.warning(f"Unknown capability: {cap_str}")

        # Get capability router
        from ..agents import get_capability_router

        router = get_capability_router()

        # Get recommendations
        recommendations = await router.get_routing_recommendations(
            required_capabilities=cap_list,
            preferred_execution_mode=execution_mode,
            limit=limit,
        )

        return recommendations

    except Exception as e:
        logger.error(f"Get routing recommendations error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Get routing recommendations error: {str(e)}"
        )


# Startup and shutdown events
@router.on_event("startup")
async def startup_event():
    """Initialize agent integration system on startup."""
    try:
        logger.info("Initializing Agent Integration API...")

        # Initialize agent integration service
        from ai_karen_engine.agents import initialize_agent_integration

        await initialize_agent_integration()

        logger.info("Agent Integration API initialized successfully")

    except Exception as e:
        logger.error(f"Agent Integration API startup error: {e}")


@router.on_event("shutdown")
async def shutdown_event():
    """Shutdown agent integration system on shutdown."""
    try:
        logger.info("Shutting down Agent Integration API...")

        # Shutdown agent integration service
        from ..agents import shutdown_agent_integration

        await shutdown_agent_integration()

        logger.info("Agent Integration API shutdown complete")

    except Exception as e:
        logger.error(f"Agent Integration API shutdown error: {e}")
