"""Queue retry and dead-letter policy.

Error classification and backoff policy independent of implementation.
No infinite poison-message loop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ErrorClass(str, Enum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    AUTHORIZATION = "authorization"
    INVALID_PAYLOAD = "invalid_payload"
    RESOURCE_MISSING = "resource_missing"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    backoff: str = "exponential"
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter: bool = True


@dataclass(frozen=True)
class RetryResult:
    should_retry: bool
    next_attempt: Optional[int] = None
    delay_seconds: Optional[float] = None
    dead_letter: bool = False
    error_class: ErrorClass = ErrorClass.PERMANENT


def classify_error(exc: Exception) -> ErrorClass:
    message = str(exc).lower()
    if "unauthorized" in message or "forbidden" in message or "403" in message:
        return ErrorClass.AUTHORIZATION
    if "invalid" in message or "bad request" in message or "400" in message:
        return ErrorClass.INVALID_PAYLOAD
    if "not found" in message or "404" in message or "missing" in message:
        return ErrorClass.RESOURCE_MISSING
    if "unavailable" in message or "timeout" in message or "502" in message or "503" in message:
        return ErrorClass.PROVIDER_UNAVAILABLE
    return ErrorClass.RETRYABLE


def compute_retry(
    policy: RetryPolicy,
    attempt: int,
    error_class: ErrorClass,
) -> RetryResult:
    if error_class in {ErrorClass.PERMANENT, ErrorClass.AUTHORIZATION, ErrorClass.INVALID_PAYLOAD}:
        return RetryResult(should_retry=False, dead_letter=True, error_class=error_class)
    if attempt >= policy.max_attempts:
        return RetryResult(should_retry=False, dead_letter=True, error_class=error_class)
    delay = _backoff(policy, attempt)
    return RetryResult(should_retry=True, next_attempt=attempt + 1, delay_seconds=delay, error_class=error_class)


def _backoff(policy: RetryPolicy, attempt: int) -> float:
    if policy.backoff == "exponential":
        delay = policy.base_delay_seconds * (2 ** attempt)
    elif policy.backoff == "linear":
        delay = policy.base_delay_seconds * (attempt + 1)
    else:
        delay = policy.base_delay_seconds
    delay = min(delay, policy.max_delay_seconds)
    if policy.jitter:
        delay *= (0.5 + random.random())
    return delay
