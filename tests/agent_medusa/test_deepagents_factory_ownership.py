"""One existing Medusa specialist changes harness; no duplicate registry entry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.agent_medusa.registry import MedusaRegistry
from ai_karen_engine.agent_medusa.registry_factory import (
    TrustedImplementationFactory,
    _register_builtins,
)
from ai_karen_engine.agent_medusa.specialists.deepagents_research_specialist import (
    DeepAgentsResearchSpecialist,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_researcher_harness_selection_preserves_agent_identity(monkeypatch, enabled):
    import ai_karen_engine.config.agent_medusa as config

    monkeypatch.setattr(
        config,
        "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(deepagents_research_enabled=enabled),
    )
    registry = MedusaRegistry()
    await registry.initialize()
    researcher = await registry.get_agent("researcher")
    agents = await registry.list_agents()
    assert len([agent for agent in agents if agent.agent_id == "researcher"]) == 1
    assert researcher.implementation_id == (
        "karen.agent.researcher.deepagents"
        if enabled else "karen.agent.researcher.native"
    )
    if enabled:
        assert researcher.prompt_contract_id == "karen.agent.researcher.deepagents"
        assert researcher.prompt_version == "v1.0.0"
    else:
        assert researcher.prompt_contract_id == "karen.agent.researcher.synthesis"


def test_trusted_factory_never_constructs_default_provider_or_duplicate_agent():
    factory = TrustedImplementationFactory()
    _register_builtins(factory)
    from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration

    registration = AgentRegistration(
        agent_id="researcher",
        name="Researcher",
        description="Researcher",
        implementation_id="karen.agent.researcher.deepagents",
    )
    specialist = factory.resolve(registration)
    assert isinstance(specialist, DeepAgentsResearchSpecialist)
    assert specialist._model_factory is None
    expected = object()
    factory.register_deepagents_model_factory(lambda *_args: expected)
    specialist = factory.resolve(registration)
    assert specialist._model_factory(registration, None) is expected


def test_trusted_factory_rejects_unregistered_implementation():
    factory = TrustedImplementationFactory()
    from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration

    with pytest.raises(ValueError, match="No trusted implementation"):
        factory.resolve(AgentRegistration(
            agent_id="unknown",
            name="Unknown",
            description="Unknown",
            implementation_id="untrusted.python.import",
        ))
