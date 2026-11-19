"""KARI-KNOW-01A: unavailable legacy knowledge is never presented as truth."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_karen_engine.services.knowledge.index_hub import (
    IndexHub,
    KnowledgeBackendUnavailableError,
    KnowledgeQuery,
)
from ai_karen_engine.api_routes.knowledge import knowledge as knowledge_routes

ROOT = Path(__file__).resolve().parents[2]
ROUTER_REGISTRY = ROOT / "src/ai_karen_engine/server/routers.py"


@pytest.mark.asyncio
async def test_unconfigured_knowledge_search_fails_closed() -> None:
    with pytest.raises(
        KnowledgeBackendUnavailableError, match="search was not performed"
    ):
        await IndexHub().search(KnowledgeQuery(text="What is company policy?"))


@pytest.mark.asyncio
async def test_unconfigured_statistics_do_not_claim_zero_sources() -> None:
    with pytest.raises(
        KnowledgeBackendUnavailableError, match="statistics were not read"
    ):
        await IndexHub().get_department_statistics()


@pytest.mark.asyncio
async def test_unconfigured_health_is_not_healthy() -> None:
    health = await IndexHub().health_check()
    assert health["status"] == "unavailable"
    assert health["indexed_sources"] is None
    assert health["reason"] == "legacy_index_not_configured"


@pytest.mark.asyncio
async def test_legacy_knowledge_route_does_not_return_empty_success(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_routes, "get_index_hub", IndexHub)
    request = knowledge_routes.KnowledgeSearchRequest(query="approved policies")
    with pytest.raises(HTTPException) as exc:
        await knowledge_routes.search_knowledge(request, user=object())
    assert exc.value.status_code == 503
    assert exc.value.detail == "Knowledge search unavailable"


@pytest.mark.asyncio
async def test_legacy_knowledge_stats_are_not_fabricated(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_routes, "get_index_hub", IndexHub)
    with pytest.raises(HTTPException) as exc:
        await knowledge_routes.get_knowledge_stats(user=object())
    assert exc.value.status_code == 503
    assert exc.value.detail == "Knowledge statistics unavailable"


@pytest.mark.asyncio
async def test_legacy_knowledge_health_is_truthful(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_routes, "get_index_hub", IndexHub)
    health = await knowledge_routes.knowledge_health_check(user=object())
    assert health["status"] == "unavailable"
    assert health["index_hub"]["status"] == "unavailable"


def test_legacy_knowledge_router_remains_unmounted() -> None:
    registry_source = ROUTER_REGISTRY.read_text(encoding="utf-8")
    tree = ast.parse(registry_source)
    assert "api_routes.knowledge.knowledge" not in registry_source
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "ai_karen_engine.api_routes.knowledge.knowledge"
        for node in ast.walk(tree)
    )
