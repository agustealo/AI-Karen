"""Atomic Redis admission regression tests without a running Redis service."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.server.rate_limiter import (
    EnhancedRateLimiter,
    RateLimitAlgorithm,
    RateLimitRule,
    RateLimitScope,
    RedisRateLimitStorage,
)


def _limiter(redis):
    storage = RedisRateLimitStorage(redis)
    rule = RateLimitRule(
        name="auth_strict",
        scope=RateLimitScope.IP_ENDPOINT,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        limit=2,
        window_seconds=60,
        endpoints=["/auth/login"],
    )
    return EnhancedRateLimiter(storage, [rule])


@pytest.mark.asyncio
async def test_atomic_admission_rejects_over_limit_and_never_double_records():
    redis = AsyncMock()
    redis.eval.side_effect = [[1, 0, 0], [1, 1, 0], [0, 2, 60]]
    limiter = _limiter(redis)
    args = dict(ip_address="127.0.0.1", endpoint="/auth/login")
    results = [await limiter.check_rate_limit(**args) for _ in range(3)]
    assert [result.allowed for result in results] == [True, True, False]
    assert results[-1].retry_after_seconds == 60
    await limiter.record_request(**args)
    assert redis.eval.await_count == 3
    assert redis.zadd.await_count == 0
    assert redis.eval.await_args.args[1] == 1


@pytest.mark.asyncio
async def test_atomic_admission_preserves_weight_and_unique_reservations():
    redis = AsyncMock()
    redis.eval.return_value = [1, 0, 0]
    storage = RedisRateLimitStorage(redis)
    await asyncio.gather(
        storage.admit_sliding_window("test", 10, 60, 3),
        storage.admit_sliding_window("test", 10, 60, 3),
    )
    calls = redis.eval.await_args_list
    assert len(calls) == 2
    assert all(call.args[6] == 3 for call in calls)
    assert calls[0].args[7] != calls[1].args[7]


@pytest.mark.asyncio
async def test_atomic_admission_propagates_redis_outage():
    redis = AsyncMock()
    redis.eval.side_effect = TimeoutError("connection timed out")
    limiter = _limiter(redis)
    with pytest.raises(TimeoutError):
        await limiter.check_rate_limit(ip_address="127.0.0.1", endpoint="/auth/login")
