"""Regression coverage: storage outages must not bypass rate limiting."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.middleware.rate_limit import rate_limit_middleware


@pytest.mark.asyncio
async def test_rate_limit_storage_failure_returns_503_without_dispatch():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/auth/login"),
        headers={},
        state=SimpleNamespace(user=None),
        client=SimpleNamespace(host="127.0.0.1"),
    )
    limiter = SimpleNamespace(check_rate_limit=AsyncMock(side_effect=TimeoutError("redis unavailable")))
    next_handler = AsyncMock()
    with patch("ai_karen_engine.middleware.rate_limit.get_rate_limiter", return_value=limiter), patch(
        "ai_karen_engine.middleware.rate_limit._extract_client_info",
        return_value=("127.0.0.1", None, None),
    ):
        response = await rate_limit_middleware(request, next_handler)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    next_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_endpoint_bypasses_rate_limiter():
    request = SimpleNamespace(url=SimpleNamespace(path="/health"), headers={})
    next_handler = AsyncMock(return_value=object())
    with patch("ai_karen_engine.middleware.rate_limit.get_rate_limiter") as limiter:
        result = await rate_limit_middleware(request, next_handler)
    assert result is next_handler.return_value
    limiter.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["/health", "/health/live", "/ready", "/metrics"])
async def test_exact_system_probes_bypass_unavailable_redis(probe):
    request = SimpleNamespace(url=SimpleNamespace(path=probe), headers={})
    response = SimpleNamespace(status_code=200)
    next_handler = AsyncMock(return_value=response)
    with patch("ai_karen_engine.middleware.rate_limit.get_rate_limiter") as limiter:
        result = await rate_limit_middleware(request, next_handler)
    assert result is response
    next_handler.assert_awaited_once_with(request)
    limiter.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("protected_path", [
    "/ready/admin", "/health/live/private", "/api/conversations",
    "/api/auth/login", "/api/copilot/assist",
])
async def test_probe_exemption_does_not_bypass_protected_rate_limits(protected_path):
    request = SimpleNamespace(
        url=SimpleNamespace(path=protected_path),
        headers={},
        state=SimpleNamespace(user=None),
        client=SimpleNamespace(host="127.0.0.1"),
    )
    limiter = SimpleNamespace(
        check_rate_limit=AsyncMock(side_effect=ConnectionError("redis unavailable"))
    )
    next_handler = AsyncMock()
    with patch(
        "ai_karen_engine.middleware.rate_limit.get_rate_limiter",
        return_value=limiter,
    ), patch(
        "ai_karen_engine.middleware.rate_limit._extract_client_info",
        return_value=("127.0.0.1", None, None),
    ):
        response = await rate_limit_middleware(request, next_handler)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    next_handler.assert_not_awaited()
