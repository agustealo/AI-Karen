"""Observability instrumentation for KAREN canonical repositories.

Emits structured events through the existing observability emitter for
every repository operation.  No sensitive data (embeddings, content,
tokens, credentials, signed URLs) is included in emitted payloads.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from src.ai_karen_engine.platform.observability.contracts import EventType as RuntimeEventType
# TODO: Fix emitter import
# from ai_karen_engine.core.observability.emitter import get_observability_emitter

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def instrument_repository(operation: str, repository: str):
    """Decorator to instrument a repository method with observability."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            status = "success"
            error_code: str | None = None
            rows_returned: int | None = None
            result: Any = None

            try:
                result = await func(*args, **kwargs)
                if hasattr(result, "success"):
                    status = "success" if result.success else "error"
                if hasattr(result, "data"):
                    data = result.data
                    if isinstance(data, list):
                        rows_returned = len(data)
                    elif data is not None and not isinstance(data, (bool, int, float, str)):
                        rows_returned = 1
                return result
            except Exception as exc:
                status = "error"
                error_code = type(exc).__name__
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                try:
                    # TODO: Fix emitter
                    # emitter = get_observability_emitter()
                    # emitter.emit(
                    #     RuntimeEventType.PERSISTENCE_COMPLETED,
                    #     intent=f"repository.{operation}",
                    #     provider=repository,
                    #     duration_ms=latency_ms,
                    #     memory_recall_count=rows_returned,
                    #     metadata={
                    #         "repository": repository,
                    #         "operation": operation,
                    #         "status": status,
                    #         "error_code": error_code,
                    #         "rows_returned": rows_returned,
                    #         "storage_backend": "postgres",
                    #     },
                    # )
                    pass
                except Exception as exc:  # pragma: no cover - observability must not break flows
                    logger.debug("Observability emission failed: %s", exc)

        return wrapper  # type: ignore[return-value]

    return decorator
