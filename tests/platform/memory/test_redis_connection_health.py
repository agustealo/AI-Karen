"""Active Redis readiness checks against the canonical platform manager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
    RedisConnectionManager,
)


@pytest.mark.asyncio
async def test_uninitialized_canonical_redis_manager_cannot_report_healthy() -> None:
    manager = RedisConnectionManager(redis_url="redis://red-private:6379")
    assert manager.is_degraded() is False
    assert manager.health() is False
    assert await manager.is_healthy() is False

    client = type("HealthyClient", (), {"ping": AsyncMock(return_value=True)})()
    manager._client = client
    assert await manager.is_healthy() is True
    client.ping.assert_awaited_once()

    manager._degraded_mode = True
    assert await manager.is_healthy() is False

    manager._degraded_mode = False
    client.ping = AsyncMock(side_effect=ConnectionError("offline"))
    assert await manager.is_healthy() is False


@pytest.mark.asyncio
async def test_redis_health_and_connection_metadata_redact_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "dont-expose-redis-secret-98765"
    url = f"redis://:{secret}@red-private:6379/0"
    manager = RedisConnectionManager(redis_url=url)
    manager._client = type(
        "BrokenClient", (),
        {"ping": AsyncMock(side_effect=ConnectionError(f"{url} unavailable"))},
    )()

    assert await manager.is_healthy() is False
    report = await manager.health_check()
    assert report["healthy"] is False
    assert report["error_type"] == "ConnectionError"
    assert report["connection_info"]["redis_url"] == "[REDACTED]"
    assert secret not in repr(report)
    assert secret not in repr(manager.get_connection_info())

    assert await manager._test_connection() is False
    assert secret not in caplog.text
