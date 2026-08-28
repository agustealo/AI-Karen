from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from ai_karen_engine.core.services.dependencies import get_current_tenant_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_context",
    [
        {},
        {"user_id": "user-1"},
        {"user_id": "user-1", "tenant_id": None},
        {"user_id": "user-1", "tenant_id": ""},
        {"user_id": "user-1", "tenant_id": "   "},
    ],
)
async def test_current_tenant_dependency_fails_closed_when_scope_is_missing(
    user_context: dict[str, Any],
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_id(user_context)

    assert exc_info.value.status_code == 401
    assert "tenant" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_current_tenant_dependency_preserves_authoritative_scope() -> None:
    tenant_id = await get_current_tenant_id(
        {"user_id": "user-1", "tenant_id": "tenant-123"}
    )

    assert tenant_id == "tenant-123"


@pytest.mark.asyncio
async def test_current_tenant_dependency_normalizes_surrounding_whitespace() -> None:
    tenant_id = await get_current_tenant_id(
        {"user_id": "user-1", "tenant_id": "  tenant-123  "}
    )

    assert tenant_id == "tenant-123"
