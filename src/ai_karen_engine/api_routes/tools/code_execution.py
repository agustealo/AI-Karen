"""
FastAPI routes for code execution and tool integration.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.tooling.code_execution_service import (
    CodeExecutionRequest,
    CodeExecutionResponse,
    CodeExecutionService,
    CodeLanguage,
    SecurityLevel,
    get_code_execution_service,
    ToolIntegrationService,
    ToolExecutionContext,
    ToolExecutionResult,
    get_tool_integration_service,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_service_error_response,
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException, Query = import_fastapi(
    "APIRouter", "Depends", "HTTPException", "Query"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = get_logger(__name__)

router = APIRouter(tags=["code-execution"])


# Alias core dependency for convenience
get_current_user = bypass_user_context_func


# Request/Response Models
class ExecuteCodeRequest(BaseModel):
    """Request for code execution."""

    code: str = Field(..., description="Code to execute")
    language: CodeLanguage = Field(..., description="Programming language")
    conversation_id: str = Field(..., description="Conversation ID")
    security_level: SecurityLevel = Field(
        SecurityLevel.STRICT, description="Security level"
    )
    execution_limits: Optional[Dict[str, Any]] = Field(
        None, description="Custom execution limits"
    )
    environment_vars: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    input_data: Optional[str] = Field(None, description="Input data for the code")


class ExecutionHistoryResponse(BaseModel):
    """Response for execution history."""

    executions: List[Dict[str, Any]] = Field(..., description="List of executions")
    total_count: int = Field(..., description="Total number of executions")


class ToolExecuteRequest(BaseModel):
    """Request for tool execution."""

    tool_name: str = Field(..., description="Name of the tool to execute")
    parameters: Dict[str, Any] = Field(..., description="Tool parameters")
    conversation_id: str = Field(..., description="Conversation ID")


class ToolListResponse(BaseModel):
    """Response for tool listing."""

    tools: List[Dict[str, Any]] = Field(..., description="List of available tools")
    categories: Dict[str, List[str]] = Field(..., description="Tool categories")
    total_count: int = Field(..., description="Total number of tools")


class ServiceStatsResponse(BaseModel):
    """Response for service statistics."""

    code_execution_stats: Dict[str, Any] = Field(
        ..., description="Code execution statistics"
    )
    tool_integration_stats: Dict[str, Any] = Field(
        ..., description="Tool integration statistics"
    )


@router.post("/execute", response_model=CodeExecutionResponse)
async def execute_code(
    request: ExecuteCodeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    code_execution_service: CodeExecutionService = Depends(get_code_execution_service),
):
    """Execute code with security controls."""
    try:
        # Create execution request
        exec_request = CodeExecutionRequest(
            code=request.code,
            language=request.language,
            user_id=current_user["user_id"],
            conversation_id=request.conversation_id,
            security_level=request.security_level,
            execution_limits=request.execution_limits,
            environment_vars=request.environment_vars,
            input_data=request.input_data,
        )

        # Execute code
        result = await code_execution_service.execute_code(exec_request)

        return result

    except Exception as e:
        logger.exception(
            "Code execution failed",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Code execution failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/languages")
async def get_supported_languages(
    code_execution_service: CodeExecutionService = Depends(get_code_execution_service),
):
    """Get list of supported programming languages."""
    try:
        code_execution_service.get_language_configs()
        return {
            "supported_languages": [
                lang.value for lang in code_execution_service.supported_languages
            ],
            "language_configs": {
                lang.value: {
                    "executable": config.get("executable"),
                    "file_extension": config.get("file_extension"),
                    "docker_image": config.get("docker_image"),
                }
                for lang, config in code_execution_service._language_configs.items()
            },
        }

    except Exception as e:
        logger.exception(
            "Failed to get supported languages",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get supported languages. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/history", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of executions"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    code_execution_service: CodeExecutionService = Depends(get_code_execution_service),
):
    """Get code execution history for the authenticated user."""
    try:
        # Get execution history from code execution service
        code_history = code_execution_service.get_execution_history(
            current_user["user_id"], limit
        )

        return ExecutionHistoryResponse(
            executions=code_history, total_count=len(code_history)
        )

    except Exception as e:
        logger.exception(
            "Failed to get execution history",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get execution history. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.delete("/execution/{execution_id}")
async def cancel_execution(
    execution_id: str,
    code_execution_service: CodeExecutionService = Depends(get_code_execution_service),
):
    """Cancel an active code execution."""
    try:
        success = await code_execution_service.cancel_execution(execution_id)

        if not success:
            error_response = create_service_error_response(
                service_name="code_execution",
                error=Exception("Execution not found or already completed"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The execution could not be found or is already completed.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "Execution cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to cancel execution",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to cancel execution. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/tools/execute", response_model=ToolExecutionResult)
async def execute_tool(
    request: ToolExecuteRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    tool_integration_service: ToolIntegrationService = Depends(
        get_tool_integration_service
    ),
):
    """Execute a registered tool."""
    try:
        # Create execution context
        context = ToolExecutionContext(
            user_id=current_user["user_id"],
            conversation_id=request.conversation_id,
            execution_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
        )

        # Execute tool
        result = await tool_integration_service.execute_tool(
            request.tool_name, request.parameters, context
        )

        return result

    except Exception as e:
        logger.exception(
            "Tool execution failed",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="tool_integration",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Tool execution failed. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(
        None, description="Search tools by name or description"
    ),
    tool_integration_service: ToolIntegrationService = Depends(
        get_tool_integration_service
    ),
):
    """List available tools."""
    try:
        if search:
            tools = tool_integration_service.search_tools(search)
        else:
            tools = tool_integration_service.get_available_tools(category)

        categories = tool_integration_service.get_categories()

        return ToolListResponse(
            tools=tools, categories=categories, total_count=len(tools)
        )

    except Exception as e:
        logger.exception(
            "Failed to list tools",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="tool_integration",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to list tools. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/tools/{tool_name}")
async def get_tool_info(
    tool_name: str,
    tool_integration_service: ToolIntegrationService = Depends(
        get_tool_integration_service
    ),
):
    """Get detailed information about a specific tool."""
    try:
        tool_info = tool_integration_service.get_tool_info(tool_name)

        if not tool_info:
            error_response = create_service_error_response(
                service_name="tool_integration",
                error=Exception("Tool not found"),
                error_code=WebAPIErrorCode.NOT_FOUND,
                user_message="The requested tool could not be found.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return tool_info

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to get tool info",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="tool_integration",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get tool information. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/tools/history", response_model=ExecutionHistoryResponse)
async def get_tool_execution_history(
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of executions"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    tool_integration_service: ToolIntegrationService = Depends(
        get_tool_integration_service
    ),
):
    """Get tool execution history for the authenticated user."""
    try:
        history = tool_integration_service.get_execution_history(
            user_id=current_user["user_id"], tool_name=tool_name, limit=limit
        )

        return ExecutionHistoryResponse(
            executions=history,
            total_count=len(history),
        )

    except Exception as e:
        logger.exception(
            "Failed to get tool execution history",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="tool_integration",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get tool execution history. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/stats", response_model=ServiceStatsResponse)
async def get_service_stats(
    code_execution_service: CodeExecutionService = Depends(get_code_execution_service),
    tool_integration_service: ToolIntegrationService = Depends(
        get_tool_integration_service
    ),
):
    """Get code execution and tool integration statistics."""
    try:
        code_stats = code_execution_service.get_service_stats()
        tool_stats = tool_integration_service.get_service_stats()

        return ServiceStatsResponse(
            code_execution_stats=code_stats, tool_integration_stats=tool_stats
        )

    except Exception as e:
        logger.exception(
            "Failed to get service stats",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get service statistics. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/security-levels")
async def get_security_levels():
    """Get available security levels and their descriptions."""
    try:
        return {
            "security_levels": [
                {
                    "level": SecurityLevel.STRICT.value,
                    "description": "Maximum security, minimal permissions",
                    "max_execution_time": 15.0,
                    "max_memory_mb": 256,
                    "allow_network": False,
                    "allow_file_system": False,
                },
                {
                    "level": SecurityLevel.MODERATE.value,
                    "description": "Balanced security and functionality",
                    "max_execution_time": 30.0,
                    "max_memory_mb": 512,
                    "allow_network": False,
                    "allow_file_system": True,
                },
                {
                    "level": SecurityLevel.PERMISSIVE.value,
                    "description": "More permissions for advanced use cases",
                    "max_execution_time": 60.0,
                    "max_memory_mb": 1024,
                    "allow_network": True,
                    "allow_file_system": True,
                },
            ]
        }

    except Exception as e:
        logger.exception(
            "Failed to get security levels",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        error_response = create_service_error_response(
            service_name="code_execution",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get security levels. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )
