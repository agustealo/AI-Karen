"""Safe error contract for Medusa execution (AGENT-LIVE-1 P0-14 / A14).

Replaces raw `f"An error occurred during execution: {str(e)}"` user-facing
content. Maps exceptions to a safe AgentError carrying:
- safe error code (never the raw message)
- correlation id
- retryability
- degradation state

Raw exception text belongs only in protected observability (logger), never in
the response returned to the user.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from ..contracts.errors import AgentErrorCode, AgentError
from ..contracts.runtime_response import RuntimeResponse, ResponseStatus

logger = logging.getLogger(__name__)


def to_safe_response(exc: Exception, *, correlation_id: Optional[str] = None) -> RuntimeResponse:
    correlation_id = correlation_id or str(uuid.uuid4())
    # Raw exception is logged to protected observability only.
    logger.error("medusa.execution_error", exc_info=exc, extra={"correlation_id": correlation_id})

    code, recoverable = _classify(exc)
    error = AgentError(
        code=code,
        message="The agent run could not be completed.",
        recoverable=recoverable,
        correlation_id=correlation_id,
        suggestions=_suggestions(code),
    )
    return RuntimeResponse(
        request_id=correlation_id,
        status=ResponseStatus.ERROR,
        content=(
            f"We hit a problem running your request (ref: {correlation_id}). "
            "Our team has been notified."
        ),
        metadata={"error_code": error.code.value, "recoverable": error.recoverable},
    )


def _classify(exc: Exception) -> tuple[AgentErrorCode, bool]:
    if isinstance(exc, ValueError):
        return AgentErrorCode.VALIDATION_ERROR, True
    if isinstance(exc, PermissionError):
        return AgentErrorCode.PERMISSION_DENIED, False
    if isinstance(exc, TimeoutError):
        return AgentErrorCode.TIMEOUT, True
    return AgentErrorCode.INTERNAL_ERROR, True


def _suggestions(code: AgentErrorCode) -> list[str]:
    return {
        AgentErrorCode.VALIDATION_ERROR: ["Check the request and try again."],
        AgentErrorCode.PERMISSION_DENIED: ["Contact an administrator for access."],
        AgentErrorCode.TIMEOUT: ["Retry with a smaller scope."],
    }.get(code, ["Please try again later."])
