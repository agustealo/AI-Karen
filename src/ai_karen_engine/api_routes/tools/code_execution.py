"""Authenticated compatibility ingress for retired execution endpoints.

The legacy URLs and request/response schemas remain recognizable to clients.
No execution or readiness is advertised until a governed runtime owns it.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ai_karen_engine.core.services.dependencies import get_user_context
from ai_karen_engine.services.tooling.code_execution_service import (
    CodeExecutionResponse,
    CodeLanguage,
    LEGACY_EXECUTION_ERROR_CODE,
    LEGACY_EXECUTION_UNAVAILABLE,
    SecurityLevel,
    ToolExecutionResult,
)

# Retain the public dependency alias while enforcing it on every endpoint.
get_current_user = get_user_context
router = APIRouter(
    tags=["code-execution"],
    dependencies=[Depends(get_current_user)],
    deprecated=True,
    responses={503: {"description": "Legacy execution is unavailable"}},
)


def _unavailable() -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "code": LEGACY_EXECUTION_ERROR_CODE,
            "message": LEGACY_EXECUTION_UNAVAILABLE,
            "execution_performed": False,
        },
    )


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
async def execute_code(request: ExecuteCodeRequest):
    _unavailable()


@router.get("/languages")
async def get_supported_languages():
    _unavailable()


@router.get("/history", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    limit: int = Query(50, ge=1, le=100),
):
    _unavailable()


@router.delete("/execution/{execution_id}")
async def cancel_execution(execution_id: str):
    _unavailable()


@router.post("/tools/execute", response_model=ToolExecutionResult)
async def execute_tool(request: ToolExecuteRequest):
    _unavailable()


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    _unavailable()


# Static history route must precede the dynamic tool-name route.
@router.get("/tools/history", response_model=ExecutionHistoryResponse)
async def get_tool_execution_history(
    tool_name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    _unavailable()


@router.get("/tools/{tool_name}")
async def get_tool_info(tool_name: str):
    _unavailable()


@router.get("/stats", response_model=ServiceStatsResponse)
async def get_service_stats():
    _unavailable()


@router.get("/security-levels")
async def get_security_levels():
    _unavailable()
