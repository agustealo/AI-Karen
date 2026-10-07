from __future__ import annotations

import logging
from typing import Any

class RuntimeLogger(logging.Logger):
    """KAREN runtime logger with structured helpers backed by stdlib logging."""

    def event(self, event_name: str, **kwargs: Any) -> None:
        """Log a structured event with the given name and metadata."""
        self.info(event_name, extra=kwargs)

    def log_event(
        self,
        *,
        event: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured runtime event."""
        payload = dict(details or {})
        if user_id is not None:
            payload["user_id"] = user_id
        self.info(event, extra=payload)

    def log_response(
        self,
        *,
        status_code: int,
        endpoint: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured transport response."""
        payload: dict[str, Any] = {
            "status_code": status_code,
            "endpoint": endpoint,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if response_data:
            payload.update(response_data)
        self.info("runtime_response", extra=payload)

    def log_error(
        self,
        *,
        error: str,
        endpoint: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        context: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured runtime error without masking the original exception."""
        payload: dict[str, Any] = {
            "endpoint": endpoint,
            "error": error,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if context is not None:
            payload["context"] = context
        if details:
            payload.update(details)
        self.error("runtime_error", extra=payload)

def get_logger(name: str | None = None) -> RuntimeLogger:
    """Return a RuntimeLogger instance for the given name."""
    if name is None:
        name = "kari.runtime"
    
    # Ensure the logger class is registered
    original_class = logging.getLoggerClass()
    logging.setLoggerClass(RuntimeLogger)
    try:
        logger = logging.getLogger(name)
    finally:
        logging.setLoggerClass(original_class)
        
    return logger # type: ignore

def configure_runtime_logging():
    """Perform initial global logging configuration."""
    from .sinks import setup_sinks
    setup_sinks()

# Compatibility aliases
StructuredLogger = RuntimeLogger
get_structured_logger = get_logger
configure_logging = configure_runtime_logging
