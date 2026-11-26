from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any

from .settings import get_logging_settings
from .formatters import RuntimeJSONFormatter, RuntimeTextFormatter
from .redaction import (
    install_request_target_privacy_filter,
    install_signed_storage_httpx_log_filter,
)

def setup_sinks():
    """Configure global logging using dictConfig for precision and to prevent duplication."""
    settings = get_logging_settings()
    
    # Ensure log directory exists
    if settings.file_enabled:
        Path(settings.file_path).parent.mkdir(parents=True, exist_ok=True)

    # Reset existing handlers to avoid duplicates
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # Define configuration
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": RuntimeJSONFormatter,
                "redact_secrets": settings.redact_secrets,
                "include_stack": settings.include_stack,
            },
            "text": {
                "()": RuntimeTextFormatter,
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json" if settings.format == "json" else "text",
            }
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console"],
                "level": settings.level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": settings.level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": settings.level,
                "propagate": False,
            },
            # Known noisy libraries
            "h11": {"level": "WARNING"},
            "asyncio": {"level": "WARNING"},
            "charset_normalizer": {"level": "WARNING"},
        },
        "root": {
            "handlers": ["console"],
            "level": settings.level,
        },
    }

    # Add file handler if enabled
    if settings.file_enabled:
        config["handlers"]["file"] = {
            "class": "logging.FileHandler",
            "filename": settings.file_path,
            "formatter": "json",
        }
        config["root"]["handlers"].append("file")
        config["loggers"]["uvicorn"]["handlers"].append("file")
        config["loggers"]["uvicorn.error"]["handlers"].append("file")

    # Apply configuration
    logging.config.dictConfig(config)
    install_signed_storage_httpx_log_filter()
    install_request_target_privacy_filter()

    # Note: OTEL and Audit forwarding sinks would be initialized here
    if settings.otel_enabled:
        # OTEL setup logic
        pass
