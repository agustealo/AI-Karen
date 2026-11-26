# mypy: ignore-errors
"""
Logging configuration for Kari FastAPI Server.
Handles logging setup, filters, and uvicorn integration.
"""

import logging
import logging.config
import os
from pathlib import Path
from typing import Any, Dict

from ai_karen_engine.core.logging.redaction import install_request_target_privacy_filter
from ai_karen_engine.server.config import Settings

_LOGGING_CONFIGURED = False


class _DedupFilter(logging.Filter):
    """Filter that drops immediate duplicate log records within a short window."""

    def __init__(self, window_seconds: float = 0.75):
        super().__init__(name="")
        self.window = window_seconds
        self._last_key: tuple | None = None
        self._last_ts: float = 0.0

    def filter(self, record: logging.LogRecord) -> bool:  # True = keep
        try:
            import time as _time

            key = (record.name, record.levelno, record.getMessage())
            now = _time.time()
            if self._last_key == key and (now - self._last_ts) <= self.window:
                return False
            self._last_key = key
            self._last_ts = now
        except Exception:
            return True
        return True


def configure_logging() -> None:
    """Configure production-grade logging"""
    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED:
        return

    Path("logs").mkdir(exist_ok=True)

    try:
        from pythonjsonlogger import jsonlogger  # type: ignore

        json_formatter: Dict[str, Any] = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s %(lineno)d %(pathname)s",
        }
    except ImportError:
        json_formatter = {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        }
    except Exception as exc:  # pragma: no cover - unexpected config issues
        logging.getLogger(__name__).exception("Unexpected logging setup error: %s", exc)
        json_formatter = {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        }

    # Allow silencing of known dev warnings via env
    _silence_dev = os.getenv("KAREN_SILENCE_DEV_WARNINGS", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    _dev_warn_level = "ERROR" if _silence_dev else "WARNING"

    # Load settings for logging configuration
    settings = Settings()

    # Clear existing handlers to avoid duplication if re-configured
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    logging.config.dictConfig(
        {
            "version": 1,
            # Disable any handlers/config that uvicorn or early imports added
            # to avoid duplicate log lines in console and files.
            "disable_existing_loggers": True,
            "filters": {
                "suppress_invalid_http": {
                    "()": "ai_karen_engine.server.logging_filters.SuppressInvalidHTTPFilter",
                },
                # Drop immediate duplicate log records in a short window
                "dedup": {
                    "()": _DedupFilter,
                    "window_seconds": 0.75,
                },
            },
            "formatters": {
                "standard": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
                "json": json_formatter,
                "access": {
                    "()": "uvicorn.logging.AccessFormatter",
                    "fmt": '%(asctime)s - %(client_addr)s - "%(request_line)s" %(status_code)s',
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": "ext://sys.stdout",
                    "filters": ["suppress_invalid_http", "dedup"],
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": "logs/kari.log",
                    "maxBytes": 10485760,
                    "backupCount": 5,
                    "formatter": "json",
                    "filters": ["suppress_invalid_http", "dedup"],
                },
                "access": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": "logs/access.log",
                    "maxBytes": 10485760,
                    "backupCount": 5,
                    "formatter": "access",
                    "filters": ["suppress_invalid_http"],
                },
                "error": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": "logs/error.log",
                    "maxBytes": 10485760,
                    "backupCount": 5,
                    "formatter": "json",
                    "level": "ERROR",
                    "filters": ["suppress_invalid_http"],
                },
            },
            "loggers": {
                "uvicorn.error": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["access"],
                    "level": "INFO",
                    "propagate": False,
                },
                # Tune development-only noisy loggers; error if silenced
                "ai_karen_engine.monitoring.model_orchestrator_tracing": {
                    "handlers": ["console", "file"],
                    "level": _dev_warn_level,
                    "propagate": False,
                },
                "kari.llm_registry": {
                    "handlers": ["console", "file"],
                    "level": _dev_warn_level,
                    "propagate": False,
                },
                "kari.memory.manager": {
                    "handlers": ["console", "file"],
                    "level": _dev_warn_level,
                    "propagate": False,
                },
                "ai_karen_engine.api_routes.memory.memory": {
                    "handlers": ["console", "file"],
                    "level": _dev_warn_level,
                    "propagate": False,
                },
                # Silence enhanced auth monitor warnings in dev if requested
                "ai_karen_engine.auth.monitoring_extensions.EnhancedAuthMonitor": {
                    "handlers": ["console", "file"],
                    "level": _dev_warn_level,
                    "propagate": False,
                },
                # Tune SQLAlchemy verbosity; avoid custom handlers so it
                # propagates to root and doesn't double-format.
                "sqlalchemy": {
                    "level": "INFO" if settings.debug else "WARNING",
                    "propagate": True,
                    "handlers": [],
                },
                "sqlalchemy.engine": {
                    "level": "INFO" if settings.debug else "WARNING",
                    "propagate": True,
                    "handlers": [],
                },
                "sqlalchemy.pool": {
                    "level": "WARNING",
                    "propagate": True,
                    "handlers": [],
                },
                # Reduce noisy per-request security logs unless elevated
                "http_requests": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "security_events": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["console", "file", "error"],
                "level": "INFO" if not settings.debug else "DEBUG",
            },
        }
    )

    install_request_target_privacy_filter()
    _LOGGING_CONFIGURED = True


def apply_uvicorn_filters() -> None:
    """Apply uvicorn-specific logging filters to reduce noise"""
    # Ensure auth audit/monitoring loggers are INFO, non-propagating, and not duplicated
    try:
        logging.getLogger("ai_karen_engine.auth.security.audit").setLevel(logging.INFO)
        logging.getLogger("ai_karen_engine.auth.security.audit").propagate = False
        logging.getLogger("ai_karen_engine.auth.monitoring.AuthMonitor").setLevel(
            logging.INFO
        )
        logging.getLogger(
            "ai_karen_engine.auth.monitoring.AuthMonitor"
        ).propagate = False
    except Exception:
        pass


# Initialize logging and create logger instance
configure_logging()
logger = logging.getLogger("kari")
