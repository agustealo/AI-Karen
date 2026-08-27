from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_karen_engine.core.services.dependencies import get_current_tenant_id


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROUTES_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "api_routes"

_SYNTHETIC_TENANT_FALLBACKS = (
    re.compile(r"tenant_id\s*=\s*str\([^\n]*\bor\s*[\"']default[\"']"),
    re.compile(r"tenant_id\s*=\s*[^\n]*\.get\(\s*[\"']tenant_id[\"']\s*\)\s*\bor\s*[\"']default[\"']"),
    re.compile(r"tenant_id\s*=\s*[\"']default[\"']"),
)


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
    user_context: dict[str, object],
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


def test_api_routes_do_not_invent_default_tenant_scope() -> None:
    violations: list[str] = []

    for path in API_ROUTES_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in _SYNTHETIC_TENANT_FALLBACKS:
            if pattern.search(source):
                violations.append(str(path.relative_to(REPO_ROOT)))
                break

    assert not violations, (
        "API ingress must never invent tenant scope. Use the canonical "
        "get_current_tenant_id dependency and fail closed instead. Violations: "
        + ", ".join(sorted(violations))
    )
