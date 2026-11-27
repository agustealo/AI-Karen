"""Retired code execution and tool integration compatibility contracts.

The legacy names remain import-compatible, but no runtime-authorized sandbox
is wired through this adapter. Never execute, validate, or report fabricated
results. Existing ToolService and ChatRuntime own their supported capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

LEGACY_EXECUTION_ERROR_CODE = "LEGACY_EXECUTION_UNAVAILABLE"
LEGACY_EXECUTION_UNAVAILABLE = (
    "This legacy execution surface has no authorized executor. "
    "No code or tool was executed."
)


class CodeLanguage(str, Enum):
    """Historical request vocabulary, not an available language catalog."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    CPP = "cpp"
    RUST = "rust"
    GO = "go"
    SHELL = "shell"
    SQL = "sql"
    JSON = "json"


class SecurityLevel(str, Enum):
    """Historical input vocabulary; no sandbox policy is granted."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    STRICT = "strict"


@dataclass
class CodeExecutionRequest:
    code: str
    language: CodeLanguage
    security_level: SecurityLevel
    timeout: int = 30
    context: Optional[Dict[str, Any]] = None


@dataclass
class CodeExecutionResponse:
    execution_id: str
    output: str
    error: Optional[str] = None
    execution_time: float = 0.0
    memory_usage: int = 0
    status: str = "unavailable"
    metadata: Optional[Dict[str, Any]] = None


class CodeExecutionService:
    """Import-compatible unavailable adapter, never an execution authority."""

    async def execute_code(
        self, request: CodeExecutionRequest
    ) -> CodeExecutionResponse:
        return CodeExecutionResponse(
            execution_id="",
            output="",
            error=LEGACY_EXECUTION_UNAVAILABLE,
            status="unavailable",
            metadata={
                "error_code": LEGACY_EXECUTION_ERROR_CODE,
                "execution_performed": False,
            },
        )

    async def get_supported_languages(self) -> List[CodeLanguage]:
        return []

    async def validate_code(self, code: str, language: CodeLanguage) -> Dict[str, Any]:
        return {
            "valid": False,
            "status": "unavailable",
            "warnings": [],
            "errors": [LEGACY_EXECUTION_UNAVAILABLE],
            "error_code": LEGACY_EXECUTION_ERROR_CODE,
        }


_service: Optional[CodeExecutionService] = None


def get_code_execution_service() -> CodeExecutionService:
    global _service
    if _service is None:
        _service = CodeExecutionService()
    return _service


@dataclass
class ToolExecutionContext:
    tool_name: str
    parameters: Dict[str, Any]
    user_id: str
    session_id: Optional[str] = None


@dataclass
class ToolExecutionResult:
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Optional[Dict[str, Any]] = None


class ToolIntegrationService:
    """Retired compatibility adapter; never dispatch to an implicit tool."""

    async def execute_tool(self, context: ToolExecutionContext) -> ToolExecutionResult:
        return ToolExecutionResult(
            success=False,
            output=None,
            error=LEGACY_EXECUTION_UNAVAILABLE,
            metadata={
                "error_code": LEGACY_EXECUTION_ERROR_CODE,
                "execution_performed": False,
            },
        )

    async def list_tools(self) -> List[Dict[str, Any]]:
        return []


_tool_service: Optional[ToolIntegrationService] = None


def get_tool_integration_service() -> ToolIntegrationService:
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolIntegrationService()
    return _tool_service
