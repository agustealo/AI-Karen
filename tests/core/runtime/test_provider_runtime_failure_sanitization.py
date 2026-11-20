"""Untrusted provider failures must never become chat text or diagnostic secrets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.provider_runtime import (
    ProviderProcessingError,
    ProviderRuntime,
)


SECRET = "sk-audit-never-export-this-value"


def test_provider_processing_error_keeps_failure_types_not_raw_contents():
    failure = ProviderProcessingError(
        "local-runtime", [RuntimeError(f"Authorization: Bearer {SECRET}")]
    )
    assert failure.last_error is not None
    assert SECRET not in str(failure)
    assert "RuntimeError" in str(failure)
    assert len(failure.errors) == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (f"Authorization: Bearer {SECRET}", "credentials or api key"),
        (f"Connection to https://private.invalid/path?token={SECRET} failed", "could not connect"),
        (f"Timed out reading prompt={SECRET}", "timed out"),
        (f"Unanticipated response: {SECRET}", "failed while handling"),
    ],
)
def test_provider_error_projection_is_allowlisted(message, expected):
    sanitized = ProviderRuntime._safe_error_detail(RuntimeError(message))
    assert expected in sanitized.lower()
    assert SECRET not in sanitized
    assert "private.invalid" not in sanitized


@pytest.mark.asyncio
async def test_provider_health_records_safe_failure_cause_without_secret():
    runtime = ProviderRuntime.__new__(ProviderRuntime)
    runtime.provider_health = {"local-runtime": {"consecutive_failures": 0}}
    runtime.latency_history_size = 5
    runtime.circuit_breaker_threshold = 10
    runtime.circuit_breaker_timeout = 10
    runtime.rate_limit_backoff = 10
    await runtime._record_provider_failure(
        "local-runtime", 0.01, RuntimeError(f"provider error {SECRET}")
    )
    health = runtime.provider_health["local-runtime"]
    assert SECRET not in health["error_message"]
    assert health["last_exception_type"] == "RuntimeError"
    assert health["consecutive_failures"] == 1


def test_emergency_result_contains_no_prompt_excerpt():
    request = SimpleNamespace(message=f"private conversation {SECRET}")
    decision = SimpleNamespace(
        requested_provider=None,
        requested_model=None,
        selected_provider=None,
        selected_model=None,
        provider_category=None,
        compatibility_profile=None,
        transport=None,
    )
    result = ProviderRuntime._build_emergency_result(
        decision=decision,
        request=request,
        correlation_id="audit-correlation",
        start_time=0.0,
        provider_attempts=[],
        degraded_message="No model is available.",
    )
    assert result.response_source == "emergency_static"
    assert result.actual_provider is None
    assert result.actual_model is None
    assert SECRET not in repr(result.metadata)
    assert "request_message" not in result.metadata
