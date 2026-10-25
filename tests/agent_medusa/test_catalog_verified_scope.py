"""Regression tests for the Medusa catalog's verified eligibility boundary."""

import pytest

from ai_karen_engine.agent_medusa.catalog import AgentCatalogService


class RecordingRegistry:
    def __init__(self):
        self.calls = 0

    async def list_agents(self):
        self.calls += 1
        return []


@pytest.mark.asyncio
async def test_missing_eligibility_scope_fails_before_registry_read():
    registry = RecordingRegistry()
    catalog = AgentCatalogService(registry)
    for scopes in (
        {},
        {"tenant_visible_ids": set(), "rbac_visible_ids": set()},
        {"tenant_visible_ids": set(), "policy_eligible_ids": set()},
        {"rbac_visible_ids": set(), "policy_eligible_ids": set()},
    ):
        with pytest.raises(PermissionError, match="agent_catalog_eligibility_scope_unverified"):
            await catalog.list_agents(require_verified_scope=True, **scopes)
    assert registry.calls == 0


@pytest.mark.asyncio
async def test_explicit_empty_scopes_are_authoritative_deny_all():
    registry = RecordingRegistry()
    catalog = AgentCatalogService(registry)
    agents = await catalog.list_agents(
        require_verified_scope=True,
        tenant_visible_ids=set(),
        rbac_visible_ids=set(),
        policy_eligible_ids=set(),
    )
    assert agents == []
    assert registry.calls == 1
