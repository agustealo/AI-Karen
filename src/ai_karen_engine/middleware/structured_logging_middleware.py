"""
Structured Logging Middleware

Integrates structured logging with HTTP requests, automatically sets correlation IDs,
tracks user actions, and feeds error aggregation service.

Requirements: 1.2, 8.5
"""

import time
import json
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ai_karen_engine.monitoring.structured_logging_service import (
    get_structured_logger,
    set_correlation_id,
    set_user_context,
    generate_correlation_id,
    clear_context,
    LogCategory,
)
from ai_karen_engine.services.monitoring.error_aggregation_service import (
    get_error_aggregation_service,
)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds structured logging to all HTTP requests.
    """

    def __init__(self, app, service_name: str = "kari-api"):
        super().__init__(app)
        self.service_name = service_name
        self.logger = get_structured_logger(service_name, "http")
        self.error_service = get_error_aggregation_service()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with structured logging"""
        start_time = time.time()

        # Generate or extract correlation ID
        correlation_id = request.headers.get("x-correlation-id")
        if not correlation_id:
            correlation_id = generate_correlation_id()

        # Set correlation context
        set_correlation_id(correlation_id)

        # Extract user information if available
        user_id = None
        session_id = None

        # Try to get user from various sources
        if hasattr(request.state, "user"):
            user_data = request.state.user
            if isinstance(user_data, dict):
                user_id = user_data.get("user_id") or user_data.get("id")
                session_id = user_data.get("session_id")

        # Check authorization header for user info
        auth_header = request.headers.get("authorization")
        if auth_header and not user_id:
            try:
                # This would need to be adapted based on your auth system
                # For now, we'll just extract basic info if available
                pass
            except Exception:
                pass

        # Set user context if available
        if user_id:
            set_user_context(user_id, session_id)

        # Extract request information
        method = request.method
        path = str(request.url.path)
        has_query = bool(request.url.query)
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")

        # Log request start
        self.logger.info(
            f"Request started: {method} {path}",
            category=LogCategory.API,
            operation="http_request_start",
            metadata={
                "method": method,
                "path": path,
                "has_query": has_query,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "correlation_id": correlation_id,
            },
        )

        try:
            # Process request
            response = await call_next(request)

            # Calculate response time
            duration_ms = (time.time() - start_time) * 1000

            # Log successful request
            self.logger.info(
                f"Request completed: {method} {path} - {response.status_code}",
                category=LogCategory.API,
                operation="http_request_complete",
                duration_ms=duration_ms,
                status_code=response.status_code,
                metadata={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "client_ip": client_ip,
                    "response_size": response.headers.get("content-length"),
                },
            )

            # Add correlation ID to response headers
            response.headers["x-correlation-id"] = correlation_id

            return response

        except Exception as e:
            # Calculate duration for failed request
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            self.logger.error(
                f"Request failed: {method} {path}",
                error=e,
                category=LogCategory.API,
                operation="http_request_error",
                metadata={
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "duration_ms": duration_ms,
                },
            )

            # Record error in aggregation service
            self.error_service.record_error(
                timestamp=time.time(),
                correlation_id=correlation_id,
                user_id=user_id,
                session_id=session_id,
                service=self.service_name,
                component="http",
                operation=f"{method} {path}",
                error_type=type(e).__name__,
                error_message=str(e),
                metadata={
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                },
            )

            # Re-raise the exception
            raise

        finally:
            # Clear context
            clear_context()

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return "unknown"


class LogCapturingHandler:
    """
    Handler that captures log records and feeds them to error aggregation service.
    """

    def __init__(self):
        self.error_service = get_error_aggregation_service()

    def handle_log_record(self, record):
        """Handle a log record and extract error information"""
        try:
            # Try to parse as structured log
            if hasattr(record, "getMessage"):
                message = record.getMessage()
                try:
                    log_data = json.loads(message)

                    # Check if this is an error log
                    if log_data.get("level") in ["error", "critical"]:
                        self.error_service.record_error(
                            timestamp=record.created,
                            correlation_id=log_data.get("correlation_id"),
                            user_id=log_data.get("user_id"),
                            session_id=log_data.get("session_id"),
                            service=log_data.get("service", "unknown"),
                            component=log_data.get("component"),
                            operation=log_data.get("operation"),
                            error_type=log_data.get("error_type", "UnknownError"),
                            error_message=log_data.get("message", ""),
                            stack_trace=log_data.get("stack_trace"),
                            metadata=log_data.get("metadata", {}),
                        )

                except json.JSONDecodeError:
                    # Handle non-JSON log records
                    if record.levelno >= 40:  # ERROR level and above
                        self.error_service.record_error(
                            timestamp=record.created,
                            correlation_id=None,
                            user_id=None,
                            session_id=None,
                            service="legacy",
                            component=record.name,
                            operation=record.funcName,
                            error_type="LegacyError",
                            error_message=message,
                            stack_trace=record.exc_text,
                            metadata={
                                "module": record.module,
                                "line": record.lineno,
                                "logger_name": record.name,
                            },
                        )

        except Exception as e:
            # Don't let logging errors break the application
            pass


# Global log handler instance
_log_handler = LogCapturingHandler()


def setup_structured_logging_integration():
    """
    Set up structured logging integration with existing logging system.
    """
    import logging

    # Create a custom handler that feeds the error aggregation service
    class ErrorAggregationHandler(logging.Handler):
        def emit(self, record):
            _log_handler.handle_log_record(record)

    # Add the handler to the root logger
    error_handler = ErrorAggregationHandler()
    error_handler.setLevel(logging.WARNING)  # Only capture warnings and errors

    root_logger = logging.getLogger()
    root_logger.addHandler(error_handler)
