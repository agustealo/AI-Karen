from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from .context import get_log_context
from .redaction import redact_data, redact_text

class RuntimeJSONFormatter(logging.Formatter):
    """JSON formatter for Kari runtime logs including context and redaction."""

    def __init__(self, redact_secrets: bool = True, include_stack: bool = False):
        super().__init__()
        self.redact_secrets = redact_secrets
        self.include_stack = include_stack

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_log_context()
        
        # Base log data
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context fields
        log_data.update(ctx.to_dict())

        # Standard LogRecord attributes to ignore when looking for extra fields
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "extra"
        }

        # Add extra fields from record (standard logging puts extra keys on the record object)
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_data[key] = value
        
        # Include specific fields if they are in record but not in context
        for key in ["correlation_id", "request_id", "user_id", "tenant_id", "provider", "model"]:
            if hasattr(record, key) and key not in log_data:
                log_data[key] = getattr(record, key)

        # Handle exceptions
        if record.exc_info:
            log_data["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "UnknownError"
            if self.include_stack:
                log_data["stack_trace"] = "".join(traceback.format_exception(*record.exc_info))
            else:
                log_data["error_message"] = str(record.exc_info[1])

        # Redaction
        if self.redact_secrets:
            log_data = redact_data(log_data)

        return json.dumps(log_data, default=str)

class RuntimeTextFormatter(logging.Formatter):
    """Minimal text formatter for development console logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        ctx = get_log_context()
        cid = ctx.correlation_id or "-"
        return f"[{record.levelname}] [{cid}] {record.name}: {redact_text(record.getMessage())}"

# Compatibility aliases
StructuredFormatter = RuntimeJSONFormatter
JSONFormatter = RuntimeJSONFormatter
