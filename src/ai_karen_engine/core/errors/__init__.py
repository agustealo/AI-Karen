"""
Unified error handling system for AI Karen engine.
"""

from ai_karen_engine.core.errors.exceptions import (
    KarenError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ServiceError,
    PluginError,
    MemoryError,
    AIProcessingError
)
from ai_karen_engine.core.errors.handlers import ErrorHandler, ErrorResponse, ErrorCode, get_error_handler
from ai_karen_engine.core.errors.middleware import error_middleware
from ai_karen_engine.core.errors.response_validation import validate_response_text

__all__ = [
    "KarenError",
    "ValidationError", 
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ServiceError",
    "PluginError",
    "MemoryError",
    "AIProcessingError",
    "ErrorHandler",
    "ErrorResponse",
    "ErrorCode",
    "get_error_handler",
    "error_middleware",
    "validate_response_text",
]