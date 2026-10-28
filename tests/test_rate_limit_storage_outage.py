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
