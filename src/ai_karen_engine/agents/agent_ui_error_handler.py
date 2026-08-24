"""
Agent UI Service Error Handler

.. deprecated::
    The legacy UI error handler is deprecated. Error handling is provided by
    the canonical runtime and Medusa failure policy.
"""

import logging
import traceback
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable

warnings.warn(
    "ai_karen_engine.agents.agent_ui_error_handler is deprecated.",
    DeprecationWarning,
    stacklevel=2,
)

from .agent_ui_models import (
    AgentUIError,
    ResponseMetadata,
    ContentType,
    LayoutType,
    OutputProfile,
)


class ErrorSeverity:
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory:
    """Error categories."""
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RESOURCE = "resource"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ErrorRecoveryStrategy:
    """Error recovery strategies."""
    RETRY = "retry"
    FALLBACK = "fallback"
    CIRCUIT_BREAKER = "circuit_breaker"
    DEGRADE = "degrade"
    FAIL_FAST = "fail_fast"
    MANUAL_INTERVENTION = "manual_intervention"


class ErrorContext:
    """Context information for errors."""
    
    def __init__(
        self,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        operation: Optional[str] = None,
        component: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize error context.
        
        Args:
            session_id: ID of the session
            task_id: ID of the task
            request_id: ID of the request
            user_id: ID of the user
            operation: Operation that caused the error
            component: Component that caused the error
            additional_context: Additional context information
        """
        self.session_id = session_id
        self.task_id = task_id
        self.request_id = request_id
        self.user_id = user_id
        self.operation = operation
        self.component = component
        self.additional_context = additional_context or {}


class AgentUIErrorHandler:
    """
    Error handler for the Agent UI Service.
    
    This class provides comprehensive error handling, including error classification,
    recovery strategies, and user-friendly error messages.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the error handler.
        
        Args:
            logger: Logger instance to use
        """
        self.logger = logger or logging.getLogger("agent_ui_error_handler")
        
        # Error code to message mapping
        self._error_messages = {
            # Validation errors
            "VALIDATION_ERROR": "Invalid request data",
            "MISSING_REQUIRED_FIELD": "Required field is missing",
            "INVALID_FIELD_VALUE": "Invalid field value",
            "INVALID_REQUEST_FORMAT": "Invalid request format",
            
            # Authentication errors
            "AUTHENTICATION_REQUIRED": "Authentication required",
            "INVALID_CREDENTIALS": "Invalid credentials",
            "SESSION_EXPIRED": "Session has expired",
            "TOKEN_INVALID": "Invalid authentication token",
            
            # Authorization errors
            "AUTHORIZATION_DENIED": "Access denied",
            "INSUFFICIENT_PERMISSIONS": "Insufficient permissions",
            "RESOURCE_ACCESS_DENIED": "Access to resource denied",
            
            # Network errors
            "NETWORK_ERROR": "Network connection error",
            "CONNECTION_TIMEOUT": "Connection timeout",
            "SERVICE_UNAVAILABLE": "Service unavailable",
            
            # Timeout errors
            "REQUEST_TIMEOUT": "Request timeout",
            "TASK_TIMEOUT": "Task execution timeout",
            "RESPONSE_TIMEOUT": "Response timeout",
            
            # Resource errors
            "RESOURCE_NOT_FOUND": "Resource not found",
            "RESOURCE_EXHAUSTED": "Resource exhausted",
            "QUOTA_EXCEEDED": "Quota exceeded",
            
            # Dependency errors
            "DEPENDENCY_ERROR": "Dependency service error",
            "AGENT_ORCHESTRATOR_ERROR": "Agent orchestrator error",
            "THREAD_MANAGER_ERROR": "Thread manager error",
            "SESSION_STATE_MANAGER_ERROR": "Session state manager error",
            "RESPONSE_FORMATTER_ERROR": "Response formatter error",
            
            # Internal errors
            "INTERNAL_ERROR": "Internal server error",
            "SERVICE_INITIALIZATION_ERROR": "Service initialization error",
            "SERVICE_SHUTDOWN_ERROR": "Service shutdown error",
            
            # Unknown errors
            "UNKNOWN_ERROR": "An unknown error occurred"
        }
        
        # Error code to recovery strategy mapping
        self._recovery_strategies = {
            # Validation errors
            "VALIDATION_ERROR": ErrorRecoveryStrategy.FAIL_FAST,
            "MISSING_REQUIRED_FIELD": ErrorRecoveryStrategy.FAIL_FAST,
            "INVALID_FIELD_VALUE": ErrorRecoveryStrategy.FAIL_FAST,
            "INVALID_REQUEST_FORMAT": ErrorRecoveryStrategy.FAIL_FAST,
            
            # Authentication errors
            "AUTHENTICATION_REQUIRED": ErrorRecoveryStrategy.MANUAL_INTERVENTION,
            "INVALID_CREDENTIALS": ErrorRecoveryStrategy.MANUAL_INTERVENTION,
            "SESSION_EXPIRED": ErrorRecoveryStrategy.MANUAL_INTERVENTION,
            "TOKEN_INVALID": ErrorRecoveryStrategy.MANUAL_INTERVENTION,
            
            # Authorization errors
            "AUTHORIZATION_DENIED": ErrorRecoveryStrategy.FAIL_FAST,
            "INSUFFICIENT_PERMISSIONS": ErrorRecoveryStrategy.FAIL_FAST,
            "RESOURCE_ACCESS_DENIED": ErrorRecoveryStrategy.FAIL_FAST,
            
            # Network errors
            "NETWORK_ERROR": ErrorRecoveryStrategy.RETRY,
            "CONNECTION_TIMEOUT": ErrorRecoveryStrategy.RETRY,
            "SERVICE_UNAVAILABLE": ErrorRecoveryStrategy.FALLBACK,
            
            # Timeout errors
            "REQUEST_TIMEOUT": ErrorRecoveryStrategy.RETRY,
            "TASK_TIMEOUT": ErrorRecoveryStrategy.FAIL_FAST,
            "RESPONSE_TIMEOUT": ErrorRecoveryStrategy.RETRY,
            
            # Resource errors
            "RESOURCE_NOT_FOUND": ErrorRecoveryStrategy.FAIL_FAST,
            "RESOURCE_EXHAUSTED": ErrorRecoveryStrategy.DEGRADE,
            "QUOTA_EXCEEDED": ErrorRecoveryStrategy.FAIL_FAST,
            
            # Dependency errors
            "DEPENDENCY_ERROR": ErrorRecoveryStrategy.RETRY,
            "AGENT_ORCHESTRATOR_ERROR": ErrorRecoveryStrategy.RETRY,
            "THREAD_MANAGER_ERROR": ErrorRecoveryStrategy.FALLBACK,
            "SESSION_STATE_MANAGER_ERROR": ErrorRecoveryStrategy.FALLBACK,
            "RESPONSE_FORMATTER_ERROR": ErrorRecoveryStrategy.FALLBACK,
            
            # Internal errors
            "INTERNAL_ERROR": ErrorRecoveryStrategy.FAIL_FAST,
            "SERVICE_INITIALIZATION_ERROR": ErrorRecoveryStrategy.FAIL_FAST,
            "SERVICE_SHUTDOWN_ERROR": ErrorRecoveryStrategy.FAIL_FAST,
            
            # Unknown errors
            "UNKNOWN_ERROR": ErrorRecoveryStrategy.FAIL_FAST
        }
        
        # Error code to category mapping
        self._error_categories = {
            # Validation errors
            "VALIDATION_ERROR": ErrorCategory.VALIDATION,
            "MISSING_REQUIRED_FIELD": ErrorCategory.VALIDATION,
            "INVALID_FIELD_VALUE": ErrorCategory.VALIDATION,
            "INVALID_REQUEST_FORMAT": ErrorCategory.VALIDATION,
            
            # Authentication errors
            "AUTHENTICATION_REQUIRED": ErrorCategory.AUTHENTICATION,
            "INVALID_CREDENTIALS": ErrorCategory.AUTHENTICATION,
            "SESSION_EXPIRED": ErrorCategory.AUTHENTICATION,
            "TOKEN_INVALID": ErrorCategory.AUTHENTICATION,
            
            # Authorization errors
            "AUTHORIZATION_DENIED": ErrorCategory.AUTHORIZATION,
            "INSUFFICIENT_PERMISSIONS": ErrorCategory.AUTHORIZATION,
            "RESOURCE_ACCESS_DENIED": ErrorCategory.AUTHORIZATION,
            
            # Network errors
            "NETWORK_ERROR": ErrorCategory.NETWORK,
            "CONNECTION_TIMEOUT": ErrorCategory.NETWORK,
            "SERVICE_UNAVAILABLE": ErrorCategory.NETWORK,
            
            # Timeout errors
            "REQUEST_TIMEOUT": ErrorCategory.TIMEOUT,
            "TASK_TIMEOUT": ErrorCategory.TIMEOUT,
            "RESPONSE_TIMEOUT": ErrorCategory.TIMEOUT,
            
            # Resource errors
            "RESOURCE_NOT_FOUND": ErrorCategory.RESOURCE,
            "RESOURCE_EXHAUSTED": ErrorCategory.RESOURCE,
            "QUOTA_EXCEEDED": ErrorCategory.RESOURCE,
            
            # Dependency errors
            "DEPENDENCY_ERROR": ErrorCategory.DEPENDENCY,
            "AGENT_ORCHESTRATOR_ERROR": ErrorCategory.DEPENDENCY,
            "THREAD_MANAGER_ERROR": ErrorCategory.DEPENDENCY,
            "SESSION_STATE_MANAGER_ERROR": ErrorCategory.DEPENDENCY,
            "RESPONSE_FORMATTER_ERROR": ErrorCategory.DEPENDENCY,
            
            # Internal errors
            "INTERNAL_ERROR": ErrorCategory.INTERNAL,
            "SERVICE_INITIALIZATION_ERROR": ErrorCategory.INTERNAL,
            "SERVICE_SHUTDOWN_ERROR": ErrorCategory.INTERNAL,
            
            # Unknown errors
            "UNKNOWN_ERROR": ErrorCategory.UNKNOWN
        }
        
        # Error code to severity mapping
        self._error_severities = {
            # Validation errors
            "VALIDATION_ERROR": ErrorSeverity.WARNING,
            "MISSING_REQUIRED_FIELD": ErrorSeverity.WARNING,
            "INVALID_FIELD_VALUE": ErrorSeverity.WARNING,
            "INVALID_REQUEST_FORMAT": ErrorSeverity.WARNING,
            
            # Authentication errors
            "AUTHENTICATION_REQUIRED": ErrorSeverity.WARNING,
            "INVALID_CREDENTIALS": ErrorSeverity.ERROR,
            "SESSION_EXPIRED": ErrorSeverity.WARNING,
            "TOKEN_INVALID": ErrorSeverity.ERROR,
            
            # Authorization errors
            "AUTHORIZATION_DENIED": ErrorSeverity.ERROR,
            "INSUFFICIENT_PERMISSIONS": ErrorSeverity.ERROR,
            "RESOURCE_ACCESS_DENIED": ErrorSeverity.ERROR,
            
            # Network errors
            "NETWORK_ERROR": ErrorSeverity.WARNING,
            "CONNECTION_TIMEOUT": ErrorSeverity.WARNING,
            "SERVICE_UNAVAILABLE": ErrorSeverity.ERROR,
            
            # Timeout errors
            "REQUEST_TIMEOUT": ErrorSeverity.WARNING,
            "TASK_TIMEOUT": ErrorSeverity.ERROR,
            "RESPONSE_TIMEOUT": ErrorSeverity.WARNING,
            
            # Resource errors
            "RESOURCE_NOT_FOUND": ErrorSeverity.WARNING,
            "RESOURCE_EXHAUSTED": ErrorSeverity.ERROR,
            "QUOTA_EXCEEDED": ErrorSeverity.ERROR,
            
            # Dependency errors
            "DEPENDENCY_ERROR": ErrorSeverity.WARNING,
            "AGENT_ORCHESTRATOR_ERROR": ErrorSeverity.ERROR,
            "THREAD_MANAGER_ERROR": ErrorSeverity.ERROR,
            "SESSION_STATE_MANAGER_ERROR": ErrorSeverity.ERROR,
            "RESPONSE_FORMATTER_ERROR": ErrorSeverity.ERROR,
            
            # Internal errors
            "INTERNAL_ERROR": ErrorSeverity.CRITICAL,
            "SERVICE_INITIALIZATION_ERROR": ErrorSeverity.CRITICAL,
            "SERVICE_SHUTDOWN_ERROR": ErrorSeverity.ERROR,
            
            # Unknown errors
            "UNKNOWN_ERROR": ErrorSeverity.ERROR
        }
        
        # Recovery handlers
        self._recovery_handlers = {
            ErrorRecoveryStrategy.RETRY: self._handle_retry,
            ErrorRecoveryStrategy.FALLBACK: self._handle_fallback,
            ErrorRecoveryStrategy.CIRCUIT_BREAKER: self._handle_circuit_breaker,
            ErrorRecoveryStrategy.DEGRADE: self._handle_degrade,
            ErrorRecoveryStrategy.FAIL_FAST: self._handle_fail_fast,
            ErrorRecoveryStrategy.MANUAL_INTERVENTION: self._handle_manual_intervention
        }
    
    def create_error(
        self,
        error_code: str,
        error_message: Optional[str] = None,
        error_details: Optional[str] = None,
        error_type: Optional[str] = None,
        context: Optional[ErrorContext] = None,
        exception: Optional[Exception] = None
    ) -> AgentUIError:
        """
        Create an Agent UI Error.
        
        Args:
            error_code: Error code
            error_message: Error message (defaults to predefined message)
            error_details: Detailed error information
            error_type: Type of the error
            context: Error context
            exception: Original exception
            
        Returns:
            Agent UI Error
        """
        # Get default message if not provided
        message = error_message or self._error_messages.get(error_code, "An unknown error occurred")
        
        # Determine error type if not provided
        if not error_type:
            error_type = self._error_categories.get(error_code, ErrorCategory.UNKNOWN)
        
        # Determine severity
        severity = self._error_severities.get(error_code, ErrorSeverity.ERROR)
        
        # Create error
        error = AgentUIError(
            error_code=error_code,
            error_message=message,
            error_details=error_details or (str(exception) if exception else None),
            error_type=error_type,
            severity=severity,
            timestamp=datetime.utcnow(),
            request_id=context.request_id if context else None,
            session_id=context.session_id if context else None,
            task_id=context.task_id if context else None,
            stack_trace=traceback.format_exc() if exception else None,
            metadata={
                "context": context.__dict__ if context else {},
                "exception_type": type(exception).__name__ if exception else None,
                "category": self._error_categories.get(error_code, ErrorCategory.UNKNOWN),
                "recovery_strategy": self._recovery_strategies.get(error_code, ErrorRecoveryStrategy.FAIL_FAST)
            }
        )
        
        return error
    
    def handle_error(
        self,
        error: Union[AgentUIError, Exception],
        context: Optional[ErrorContext] = None,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> AgentUIError:
        """
        Handle an error.
        
        Args:
            error: The error to handle
            context: Error context
            recovery_callback: Optional callback for recovery
            
        Returns:
            Handled Agent UI Error
        """
        # Convert exception to AgentUIError if needed
        if not isinstance(error, AgentUIError):
            agent_ui_error = self.create_error(
                error_code="UNKNOWN_ERROR",
                error_message=str(error),
                context=context,
                exception=error
            )
        else:
            agent_ui_error = error
        
        # Log the error
        self._log_error(agent_ui_error)
        
        # Get recovery strategy
        recovery_strategy = agent_ui_error.metadata.get("recovery_strategy", ErrorRecoveryStrategy.FAIL_FAST)
        
        # Apply recovery strategy
        recovery_handler = self._recovery_handlers.get(recovery_strategy)
        if recovery_handler:
            try:
                recovery_result = recovery_handler(agent_ui_error, recovery_callback)
                if recovery_result:
                    agent_ui_error.metadata["recovery_result"] = recovery_result
            except Exception as recovery_error:
                self.logger.error(f"Error during recovery: {recovery_error}")
                agent_ui_error.metadata["recovery_error"] = str(recovery_error)
        
        return agent_ui_error
    
    def _log_error(self, error: AgentUIError) -> None:
        """
        Log an error.
        
        Args:
            error: The error to log
        """
        # Format log message
        log_message = f"Error {error.error_code}: {error.error_message}"
        if error.error_details:
            log_message += f" - {error.error_details}"
        
        # Log with appropriate level
        if error.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(log_message, extra={"error": error.model_dump()})
        elif error.severity == ErrorSeverity.ERROR:
            self.logger.error(log_message, extra={"error": error.model_dump()})
        elif error.severity == ErrorSeverity.WARNING:
            self.logger.warning(log_message, extra={"error": error.model_dump()})
        else:
            self.logger.info(log_message, extra={"error": error.model_dump()})
    
    async def _handle_retry(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle retry recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "retry", "success": False}
        
        if recovery_callback:
            try:
                recovery_result = await recovery_callback(error)
                result["success"] = True
                result["recovery_result"] = recovery_result
            except Exception as e:
                result["error"] = str(e)
        
        return result
    
    async def _handle_fallback(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle fallback recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "fallback", "success": False}
        
        if recovery_callback:
            try:
                recovery_result = await recovery_callback(error)
                result["success"] = True
                result["recovery_result"] = recovery_result
            except Exception as e:
                result["error"] = str(e)
        
        return result
    
    async def _handle_circuit_breaker(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle circuit breaker recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "circuit_breaker", "success": False, "message": "Circuit breaker triggered"}
        
        # In a real implementation, this would involve circuit breaker logic
        # For now, we'll just log and return a result
        
        self.logger.warning(f"Circuit breaker triggered for error: {error.error_code}")
        
        return result
    
    async def _handle_degrade(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle degrade recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "degrade", "success": False, "message": "Service degraded"}
        
        if recovery_callback:
            try:
                recovery_result = await recovery_callback(error)
                result["success"] = True
                result["recovery_result"] = recovery_result
            except Exception as e:
                result["error"] = str(e)
        
        return result
    
    async def _handle_fail_fast(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle fail fast recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "fail_fast", "success": False, "message": "Failed fast"}
        
        # Fail fast means we don't attempt recovery
        # Just log and return
        
        self.logger.info(f"Failed fast for error: {error.error_code}")
        
        return result
    
    async def _handle_manual_intervention(
        self,
        error: AgentUIError,
        recovery_callback: Optional[Callable[[AgentUIError], Awaitable[Any]]] = None
    ) -> Dict[str, Any]:
        """
        Handle manual intervention recovery strategy.
        
        Args:
            error: The error to handle
            recovery_callback: Optional callback for recovery
            
        Returns:
            Recovery result
        """
        result = {"strategy": "manual_intervention", "success": False, "message": "Manual intervention required"}
        
        # Manual intervention means we don't attempt recovery
        # Just log and return
        
        self.logger.warning(f"Manual intervention required for error: {error.error_code}")
        
        return result
    
    def create_error_response_metadata(self, error: AgentUIError) -> ResponseMetadata:
        """
        Create response metadata for an error.
        
        Args:
            error: The error
            
        Returns:
            Response metadata
        """
        return ResponseMetadata(
            response_id=str(error.timestamp.timestamp()),
            content_type=ContentType.TEXT,
            layout_type=LayoutType.DEFAULT,
            output_profile=OutputProfile.PLAIN,
            has_error=True,
            metadata={
                "error_code": error.error_code,
                "error_type": error.error_type,
                "error_severity": error.severity,
                "error_category": error.metadata.get("category", ErrorCategory.UNKNOWN)
            }
        )
    
    def get_user_friendly_error_message(self, error: AgentUIError) -> str:
        """
        Get a user-friendly error message.
        
        Args:
            error: The error
            
        Returns:
            User-friendly error message
        """
        # Base message
        message = error.error_message
        
        # Add suggestions based on error code
        suggestions = self._get_error_suggestions(error.error_code)
        if suggestions:
            message += "\n\nSuggestions:\n"
            for suggestion in suggestions:
                message += f"- {suggestion}\n"
        
        return message
    
    def _get_error_suggestions(self, error_code: str) -> List[str]:
        """
        Get suggestions for an error code.
        
        Args:
            error_code: The error code
            
        Returns:
            List of suggestions
        """
        suggestions = {
            # Validation errors
            "VALIDATION_ERROR": ["Check your input data and try again"],
            "MISSING_REQUIRED_FIELD": ["Provide all required fields"],
            "INVALID_FIELD_VALUE": ["Check the field values and try again"],
            "INVALID_REQUEST_FORMAT": ["Check the request format and try again"],
            
            # Authentication errors
            "AUTHENTICATION_REQUIRED": ["Please authenticate and try again"],
            "INVALID_CREDENTIALS": ["Check your credentials and try again"],
            "SESSION_EXPIRED": ["Please log in again"],
            "TOKEN_INVALID": ["Please authenticate again"],
            
            # Authorization errors
            "AUTHORIZATION_DENIED": ["You don't have permission to perform this action"],
            "INSUFFICIENT_PERMISSIONS": ["Contact your administrator for additional permissions"],
            "RESOURCE_ACCESS_DENIED": ["You don't have access to this resource"],
            
            # Network errors
            "NETWORK_ERROR": ["Check your network connection and try again"],
            "CONNECTION_TIMEOUT": ["Check your network connection and try again"],
            "SERVICE_UNAVAILABLE": ["Try again later or contact support"],
            
            # Timeout errors
            "REQUEST_TIMEOUT": ["Try again with a simpler request"],
            "TASK_TIMEOUT": ["Try again with a smaller task or increase timeout"],
            "RESPONSE_TIMEOUT": ["Try again later"],
            
            # Resource errors
            "RESOURCE_NOT_FOUND": ["Check the resource identifier and try again"],
            "RESOURCE_EXHAUSTED": ["Try again later or contact support"],
            "QUOTA_EXCEEDED": ["Wait for quota reset or contact support"],
            
            # Dependency errors
            "DEPENDENCY_ERROR": ["Try again later or contact support"],
            "AGENT_ORCHESTRATOR_ERROR": ["Try again later or contact support"],
            "THREAD_MANAGER_ERROR": ["Try again later or contact support"],
            "SESSION_STATE_MANAGER_ERROR": ["Try again later or contact support"],
            "RESPONSE_FORMATTER_ERROR": ["Try again later or contact support"],
            
            # Internal errors
            "INTERNAL_ERROR": ["Try again later or contact support"],
            "SERVICE_INITIALIZATION_ERROR": ["Try again later or contact support"],
            "SERVICE_SHUTDOWN_ERROR": ["Try again later or contact support"],
            
            # Unknown errors
            "UNKNOWN_ERROR": ["Try again later or contact support"]
        }
        
        return suggestions.get(error_code, [])