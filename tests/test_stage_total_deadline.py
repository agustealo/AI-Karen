"""Resilience policies must bound all attempts within one stage deadline."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_karen_engine.core.runtime.resilience.safe_stage_runner import SafeStageRunner


@pytest.mark.asyncio
async def test_stage_deadline_prevents_retry_after_timeout():
    runner = SafeStageRunner()
    runner.flags = SimpleNamespace(is_enabled=lambda *args: True)
    runner.breakers = SimpleNamespace(get_breaker=lambda name: SimpleNamespace(
        allow_request=lambda: True, record_failure=lambda: None, record_success=lambda: None,
    ))
    runner.policies = SimpleNamespace(get_policy=lambda name: SimpleNamespace(
        timeout_seconds=0.02, max_retries=3,
    ))
    runner.fallbacks = SimpleNamespace(get_fallback=lambda *args, **kwargs: "degraded")
    calls = 0

    async def slow_stage():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)

    result = await runner.run_stage("spacy", "spacy", slow_stage)
    assert result == "degraded"
    assert calls == 1


def test_spacy_policy_disables_retry_amplification():
    from ai_karen_engine.core.runtime.resilience.pipeline_policy import get_pipeline_policy

    policy = get_pipeline_policy().get_policy("spacy")
    assert policy.max_retries == 0
    assert policy.timeout_seconds == 2.0
