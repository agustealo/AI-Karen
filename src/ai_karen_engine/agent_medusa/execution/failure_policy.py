"""Execution failure / cancellation policy (AGENT-LIVE-1 A16).

Defines deterministic behavior when a step (or its siblings) fail during
parallel execution, instead of inheriting asyncio.gather() default semantics:

- one specialist fails -> defined policy: cancel siblings / continue
  independent siblings / return partial / retry
- partial success materializes as ResponseStatus.PARTIAL / DEGRADED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from ..contracts.runtime_response import ResponseStatus


class SiblingFailurePolicy(str, Enum):
    CANCEL_SIBLINGS = "cancel_siblings"
    CONTINUE_INDEPENDENT = "continue_independent"
    PARTIAL_RESULT = "partial_result"
    RETRY = "retry"


@dataclass
class ExecutionFailurePolicy:
    on_sibling_failure: SiblingFailurePolicy = SiblingFailurePolicy.CONTINUE_INDEPENDENT
    allow_partial: bool = True
    max_retries: int = 0

    def resolve_status(self, *, completed: int, failed: int, total: int) -> ResponseStatus:
        if failed == 0 and completed == total:
            return ResponseStatus.SUCCESS
        if completed == 0:
            return ResponseStatus.ERROR
        if self.allow_partial:
            return ResponseStatus.PARTIAL
        return ResponseStatus.DEGRADED


def aggregate_status(step_statuses: List[str]) -> ResponseStatus:
    """Map a set of step statuses to a final response status (uses RuntimeResponse)."""
    if not step_statuses:
        return ResponseStatus.ERROR
    if all(s == "completed" for s in step_statuses):
        return ResponseStatus.SUCCESS
    if any(s == "failed" for s in step_statuses) and any(s == "completed" for s in step_statuses):
        return ResponseStatus.PARTIAL
    if any(s == "failed" for s in step_statuses):
        return ResponseStatus.ERROR
    return ResponseStatus.DEGRADED
