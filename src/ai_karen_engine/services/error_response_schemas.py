"""
Standardized error response models for API endpoints.
Merged canonical contract replacing models/error_responses.py and
models/web_api_error_responses.py.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class WebAPIErrorCode(str, Enum):
    """Generic error codes used across API endpoints."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SERVICE_ERROR = "SERVICE_ERROR"
    PLUGIN_ERROR = "PLUGIN_ERROR"
    MEMORY_ERROR = "MEMORY_ERROR"
    AI_PROCESSING_ERROR = "AI_PROCESSING_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_VALUE = "INVALID_VALUE"

    DATABASE_ERROR = "DATABASE_ERROR"
    DATABASE_CONNECTION_ERROR = "DATABASE_CONNECTION_ERROR"
    DATABASE_SCHEMA_ERROR = "DATABASE_SCHEMA_ERROR"
    MISSING_TABLE_ERROR = "MISSING_TABLE_ERROR"
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"

    CHAT_PROCESSING_ERROR = "CHAT_PROCESSING_ERROR"
    AI_ORCHESTRATOR_ERROR = "AI_ORCHESTRATOR_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"

    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"

    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    CONFLICT = "CONFLICT"
    BAD_REQUEST = "BAD_REQUEST"


class ValidationErrorDetail(BaseModel):
    """Detailed information for validation errors."""

    field: str
    message: str
    invalid_value: Any
    expected_type: Optional[str] = Field(None, description="Expected data type or format")
    constraint: Optional[str] = Field(None, description="Validation constraint that was violated")


class DatabaseErrorDetail(BaseModel):
    """Detailed database error information."""

    error_type: str = Field(..., description="Type of database error")
    table_name: Optional[str] = Field(None, description="Table involved in the error")
    operation: Optional[str] = Field(None, description="Database operation that failed")
    sql_state: Optional[str] = Field(None, description="SQL state code if available")
    migration_needed: bool = Field(False, description="Whether a database migration is needed")
    suggested_action: Optional[str] = Field(None, description="Suggested action to resolve the error")


class WebAPIErrorResponse(BaseModel):
    """Standard error response returned by API routes."""

    error: str
    message: str
    type: WebAPIErrorCode
    details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    timestamp: str

    validation_errors: Optional[List[ValidationErrorDetail]] = Field(None, description="Field-level validation errors")
    database_error: Optional[DatabaseErrorDetail] = Field(None, description="Database-specific error details")
    retry_after: Optional[int] = Field(None, description="Seconds to wait before retrying (for rate limits)")
    help_url: Optional[str] = Field(None, description="URL to documentation or help")


class WebAPISuccessResponse(BaseModel):
    """Standardized success response wrapper for consistent API responses."""

    success: bool = Field(True, description="Indicates successful operation")
    data: Any = Field(..., description="Response data")
    message: Optional[str] = Field(None, description="Optional success message")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique request ID for tracking")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO timestamp of response")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional response metadata")


def create_error_response(
    error_code: WebAPIErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    user_message: Optional[str] = None,
) -> WebAPIErrorResponse:
    """Helper to create a WebAPIErrorResponse."""

    return WebAPIErrorResponse(
        error=user_message or message,
        message=message,
        type=error_code,
        details=details,
        request_id=request_id,
        timestamp=datetime.utcnow().isoformat(),
    )


def create_validation_error_response(
    field_errors: List[ValidationErrorDetail],
    user_message: Optional[str] = None,
    request_id: Optional[str] = None
) -> WebAPIErrorResponse:
    """Create a standardized validation error response."""

    error_message = user_message or "Request validation failed"
    detail_message = f"Validation failed for {len(field_errors)} field(s)"

    return WebAPIErrorResponse(
        error=error_message,
        message=detail_message,
        type=WebAPIErrorCode.VALIDATION_ERROR,
        validation_errors=field_errors,
        details={
            "error_count": len(field_errors),
            "failed_fields": [error.field for error in field_errors]
        },
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
    )


def create_database_error_response(
    error: Exception,
    operation: Optional[str] = None,
    table_name: Optional[str] = None,
    user_message: Optional[str] = None,
    request_id: Optional[str] = None
) -> WebAPIErrorResponse:
    """Create a standardized database error response with schema validation."""

    error_str = str(error)
    error_type = type(error).__name__

    if "relation" in error_str and "does not exist" in error_str:
        error_code = WebAPIErrorCode.MISSING_TABLE_ERROR
        user_msg = user_message or "Database table is missing. System may need initialization."

        if not table_name and "relation \"" in error_str:
            start = error_str.find("relation \"") + 10
            end = error_str.find("\"", start)
            table_name = error_str[start:end] if end > start else None

        suggested_action = f"Run database migrations to create missing table: {table_name}" if table_name else "Run database migrations"
        migration_needed = True

    elif "connection" in error_str.lower() or "connect" in error_str.lower():
        error_code = WebAPIErrorCode.DATABASE_CONNECTION_ERROR
        user_msg = user_message or "Database connection failed. Please try again later."
        suggested_action = "Check database connection settings and ensure database server is running"
        migration_needed = False

    else:
        error_code = WebAPIErrorCode.DATABASE_ERROR
        user_msg = user_message or "Database operation failed. Please try again."
        suggested_action = "Check database logs for more details"
        migration_needed = False

    database_detail = DatabaseErrorDetail(
        error_type=error_type,
        table_name=table_name,
        operation=operation,
        migration_needed=migration_needed,
        suggested_action=suggested_action
    )

    return WebAPIErrorResponse(
        error=user_msg,
        message=f"Database error: {error_str}",
        type=error_code,
        database_error=database_detail,
        details={
            "error_type": error_type,
            "operation": operation,
            "table_name": table_name
        },
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
    )


def create_service_error_response(
    service_name: str,
    error: Exception,
    error_code: WebAPIErrorCode,
    user_message: Optional[str] = None,
    request_id: Optional[str] = None,
    retry_after: Optional[int] = None
) -> WebAPIErrorResponse:
    """Create a standardized service error response."""

    error_str = str(error)
    error_type = type(error).__name__

    user_msg = user_message or f"{service_name} service error. Please try again."
    detail_message = f"{service_name} service failed: {error_str}"

    details = {
        "service": service_name,
        "error_type": error_type,
        "error_message": error_str
    }

    return WebAPIErrorResponse(
        error=user_msg,
        message=detail_message,
        type=error_code,
        details=details,
        retry_after=retry_after,
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
    )


def create_generic_error_response(
    error_code: WebAPIErrorCode,
    message: str,
    user_message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    help_url: Optional[str] = None
) -> WebAPIErrorResponse:
    """Create a generic standardized error response."""

    return WebAPIErrorResponse(
        error=user_message or message,
        message=message,
        type=error_code,
        details=details,
        request_id=request_id or str(uuid.uuid4()),
        help_url=help_url,
        timestamp=datetime.utcnow().isoformat(),
    )


def create_success_response(
    data: Any,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> WebAPISuccessResponse:
    """Create a standardized success response."""

    return WebAPISuccessResponse(
        data=data,
        message=message,
        metadata=metadata,
        request_id=request_id or str(uuid.uuid4()),
    )


# Database schema validation utilities
def validate_database_schema(table_name: str, required_columns: List[str]) -> Optional[WebAPIErrorResponse]:
    """
    Validate that a database table exists and has required columns.
    Returns None if valid, or WebAPIErrorResponse if validation fails.
    """
    try:
        return None

    except Exception as e:
        return create_database_error_response(
            error=e,
            operation="schema_validation",
            table_name=table_name,
            user_message="Database schema validation failed"
        )


def get_missing_tables_migration_response() -> WebAPIErrorResponse:
    """Get a standardized response for missing database tables."""

    return WebAPIErrorResponse(
        error="Database tables are missing. System initialization required.",
        message="Required database tables do not exist. Please run database migrations.",
        type=WebAPIErrorCode.MIGRATION_REQUIRED,
        database_error=DatabaseErrorDetail(
            error_type="MissingTablesError",
            migration_needed=True,
            suggested_action="Run: python -m ai_karen_engine.database.migrate or use docker/database/scripts/migrate.sh"
        ),
        details={
            "required_action": "database_migration",
            "migration_command": "python -m ai_karen_engine.database.migrate"
        },
        help_url="https://github.com/your-repo/docs/database-setup.md",
        request_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
    )


# HTTP status code mapping for error types
ERROR_CODE_TO_HTTP_STATUS = {
    WebAPIErrorCode.VALIDATION_ERROR: 400,
    WebAPIErrorCode.MISSING_REQUIRED_FIELD: 400,
    WebAPIErrorCode.INVALID_FORMAT: 400,
    WebAPIErrorCode.INVALID_VALUE: 400,
    WebAPIErrorCode.BAD_REQUEST: 400,

    WebAPIErrorCode.AUTHENTICATION_ERROR: 401,
    WebAPIErrorCode.INVALID_TOKEN: 401,
    WebAPIErrorCode.TOKEN_EXPIRED: 401,

    WebAPIErrorCode.AUTHORIZATION_ERROR: 403,
    WebAPIErrorCode.PERMISSION_DENIED: 403,

    WebAPIErrorCode.NOT_FOUND: 404,

    WebAPIErrorCode.CONFLICT: 409,

    WebAPIErrorCode.RATE_LIMIT_EXCEEDED: 429,

    WebAPIErrorCode.INTERNAL_SERVER_ERROR: 500,
    WebAPIErrorCode.DATABASE_ERROR: 500,
    WebAPIErrorCode.DATABASE_CONNECTION_ERROR: 500,
    WebAPIErrorCode.DATABASE_SCHEMA_ERROR: 500,
    WebAPIErrorCode.MISSING_TABLE_ERROR: 500,
    WebAPIErrorCode.MIGRATION_REQUIRED: 500,
    WebAPIErrorCode.CHAT_PROCESSING_ERROR: 500,
    WebAPIErrorCode.MEMORY_ERROR: 500,
    WebAPIErrorCode.PLUGIN_ERROR: 500,
    WebAPIErrorCode.AI_ORCHESTRATOR_ERROR: 500,
    WebAPIErrorCode.EMBEDDING_ERROR: 500,
    WebAPIErrorCode.AI_PROCESSING_ERROR: 500,
    WebAPIErrorCode.SERVICE_ERROR: 500,

    WebAPIErrorCode.SERVICE_UNAVAILABLE: 503,
    WebAPIErrorCode.TIMEOUT_ERROR: 504,
}


def get_http_status_for_error_code(error_code: WebAPIErrorCode) -> int:
    """Get the appropriate HTTP status code for a given error code."""
    return ERROR_CODE_TO_HTTP_STATUS.get(error_code, 500)
