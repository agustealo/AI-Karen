"""Native analyst output must be observed, schema-valid and safely logged."""

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.specialists import analyst_specialist
from ai_karen_engine.agent_medusa.specialists.analyst_specialist import AnalystSpecialist


@pytest.fixture
def bridge(monkeypatch):
    invoke = AsyncMock()
    monkeypatch.setattr(
        analyst_specialist.GenerationBridge, "invoke", invoke
    )
    return invoke


@pytest.mark.asyncio
@pytest.mark.parametrize("research", [True, False])
async def test_analyst_preserves_valid_observed_result(bridge, research):
    import json

    bridge.return_value = json.dumps({
        "intent": "information_request",
        "key_terms": ["observed"],
        "requires_research": research,
    })
    result = await AnalystSpecialist().run({"query": "private-query"})
    assert result == {
        "intent": "information_request",
        "structured_query": {"raw": "private-query", "key_terms": ["observed"]},
        "suggested_next_specialist": "researcher" if research else None,
    }
    assert bridge.await_args.kwargs["prompt_version"] == "v1.0.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    "not JSON",
    "{}",
    '{"intent":"", "key_terms":[], "requires_research":false}',
    '{"intent":"query", "key_terms":"wrong", "requires_research":false}',
    '{"intent":"query", "key_terms":[1], "requires_research":false}',
    '{"intent":"query", "key_terms":[], "requires_research":"false"}',
])
async def test_analyst_invalid_output_never_becomes_success(bridge, response, caplog):
    caplog.set_level("INFO")
    bridge.return_value = response
    with pytest.raises(ValueError):
        await AnalystSpecialist().run({"query": "private-query?"})
    assert "private-query" not in caplog.text
    assert "medusa_analyst_analysis_failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [PermissionError, RuntimeError])
async def test_analyst_preserves_failure_without_logging_private_details(
    bridge, error_type, caplog
):
    caplog.set_level("INFO")
    failure = error_type("private-provider-detail")
    bridge.side_effect = failure
    with pytest.raises(error_type) as raised:
        await AnalystSpecialist().run({"query": "private-query?"})
    assert raised.value is failure
    assert "private-query" not in caplog.text
    assert "private-provider-detail" not in caplog.text
    assert "medusa_specialist_execution_failed" in caplog.text


@pytest.fixture
def research_bridges(monkeypatch, tmp_path):
    from ai_karen_engine.agent_medusa.specialists import researcher_specialist
    from ai_karen_engine.core.runtime import prompt

    service = prompt.PromptRuntimeService(registry=prompt.PromptRegistry(tmp_path))
    monkeypatch.setattr(prompt, "get_prompt_runtime_service", lambda: service)

    tool = AsyncMock()
    generate = AsyncMock()
    monkeypatch.setattr(researcher_specialist.ToolBridge, "execute", tool)
    monkeypatch.setattr(researcher_specialist.GenerationBridge, "invoke", generate)
    return tool, generate


@pytest.fixture
def research_execution():
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionTopology
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import (
        SpecialistExecutionContext,
    )

    return SpecialistExecutionContext(
        authorized_plan=AuthorizedExecutionPlan(
            execution_id="request", policy_decision_id="policy",
            authorized_user_id="user", authorized_tenant_id="tenant",
            topology=ExecutionTopology.MULTI_AGENT,
            allowed_agents=["researcher"], allowed_tools=["web_search"],
            provider_constraints={"provider": "local"},
        ),
        tenant_id="tenant", user_id="user", policy_decision_id="policy",
        trajectory_id="request", correlation_id="correlation", step_id="research",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"success": False}, {"success": 1}, {"success": True}, {"success": True, "result": None}])
async def test_researcher_rejects_unacknowledged_evidence(research_bridges, research_execution, result):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist

    tool, generate = research_bridges
    tool.return_value = result
    with pytest.raises(RuntimeError):
        await ResearcherSpecialist().run({"query": "query"}, execution=research_execution)
    generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["tool", "generation"])
@pytest.mark.parametrize("error", [PermissionError, RuntimeError])
async def test_researcher_propagates_denied_or_failed_stage(research_bridges, research_execution, stage, error, caplog):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist

    tool, generate = research_bridges
    tool.return_value = {"success": True, "result": ["private-evidence"]}
    failure = error("private-failure")
    (tool if stage == "tool" else generate).side_effect = failure
    with pytest.raises(error) as raised:
        await ResearcherSpecialist().run({"query": "private-query"}, execution=research_execution)
    assert raised.value is failure
    assert "private-failure" not in caplog.text
    assert "private-evidence" not in caplog.text
    if stage == "tool":
        generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [[], ["observed"]])
async def test_researcher_preserves_acknowledged_evidence(research_bridges, research_execution, evidence):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist

    tool, generate = research_bridges
    tool.return_value = {"success": True, "result": evidence}
    generate.return_value = "Observed synthesis"
    result = await ResearcherSpecialist().run({"query": "query"}, execution=research_execution)
    assert result == {
        "search_results": [{"tool": "web_search", "result": evidence}],
        "context_found": "Observed synthesis",
    }
    assert generate.await_args.kwargs["prompt_version"] == "v1.0.0"
    assert tool.await_args.kwargs["execution"] is research_execution
    assert generate.await_args.kwargs["execution"] is research_execution
    assert generate.await_args.kwargs["provider_constraints"] == {"provider": "local"}
    assert generate.await_args.kwargs["model_constraints"] == {}


@pytest.mark.asyncio
async def test_researcher_missing_authority_never_dispatches(research_bridges):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist

    tool, generate = research_bridges
    with pytest.raises(PermissionError):
        await ResearcherSpecialist().run({"query": "query"})
    tool.assert_not_awaited()
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_researcher_empty_synthesis_never_succeeds(research_bridges, research_execution):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist

    tool, generate = research_bridges
    tool.return_value = {"success": True, "result": ["observed"]}
    generate.return_value = " "
    with pytest.raises(RuntimeError, match="researcher_synthesis_empty"):
        await ResearcherSpecialist().run({"query": "query"}, execution=research_execution)


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id, prompt_id", [
    ("analyst", "karen.agent.analyst.intent"),
    ("researcher", "karen.agent.researcher.synthesis"),
])
async def test_native_contract_is_assembled_once(tmp_path, monkeypatch, agent_id, prompt_id):
    from ai_karen_engine.core.runtime.prompt import PromptRegistry, PromptRuntimeService
    from ai_karen_engine.agent_medusa.registry import MedusaRegistry

    service = PromptRuntimeService(registry=PromptRegistry(tmp_path))
    definition = service.require_active_prompt_definition(prompt_id, "v1.0.0")
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "private input"}],
        integrated_context={},
        prompt_id=prompt_id,
        prompt_version="v1.0.0",
        token_budget=4096,
    )
    result = await service.assemble_prompt(request, require_registered=True)
    assert sum(definition.system_instructions in m["content"] for m in result.messages) == 1
    assert result.messages[-1]["content"] == "private input"
    from ai_karen_engine.config import agent_medusa

    monkeypatch.setattr(agent_medusa, "_SETTINGS", agent_medusa.AgentMedusaRuntimeSettings())
    registry = MedusaRegistry()
    await registry.initialize()
    registration = await registry.get_agent(agent_id)
    assert registration is not None
    assert registration.prompt_contract_id == prompt_id
    assert registration.prompt_version == definition.version


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_id, version", [
    (None, None),
    ("missing.prompt", "v1.0.0"),
    ("karen.agent.analyst.intent", None),
    ("karen.agent.analyst.intent", "v9.0.0"),
    ("karen.chat.default", "v1.0.0"),
])
async def test_strict_prompt_assembly_never_uses_unregistered_fallback(tmp_path, prompt_id, version):
    from ai_karen_engine.core.runtime.prompt import PromptNotFoundError, PromptRegistry, PromptRuntimeService

    service = PromptRuntimeService(registry=PromptRegistry(tmp_path))
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "query"}],
        integrated_context={},
        prompt_id=prompt_id,
        prompt_version=version,
        token_budget=4096,
    )
    with pytest.raises(PromptNotFoundError):
        await service.assemble_prompt(request, require_registered=True)


@pytest.mark.asyncio
async def test_researcher_missing_prompt_never_dispatches(research_bridges, research_execution, monkeypatch):
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import ResearcherSpecialist
    from ai_karen_engine.core.runtime.prompt import PromptNotFoundError

    monkeypatch.setattr(ResearcherSpecialist, "PROMPT_VERSION", "v9.0.0")
    tool, generate = research_bridges
    with pytest.raises(PromptNotFoundError):
        await ResearcherSpecialist().run({"query": "query"}, execution=research_execution)
    tool.assert_not_awaited()
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_registered_prompt_budget_counts_definition_and_final_messages(tmp_path):
    from ai_karen_engine.core.runtime.prompt import PromptRegistry, PromptRuntimeService
    from ai_karen_engine.core.runtime.prompt.prompt_contract import (
        PromptDefinition, PromptLifecycleStatus,
    )

    registry = PromptRegistry(tmp_path)
    registry.register_prompt(PromptDefinition(
        prompt_id="test.native.budget", version="v1.0.0", name="Budget proof",
        system_instructions="protected instruction " * 1000,
        status=PromptLifecycleStatus.ACTIVE,
    ))
    service = PromptRuntimeService(registry=registry)
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "query"}],
        integrated_context={}, prompt_id="test.native.budget",
        prompt_version="v1.0.0", token_budget=512,
    )
    assert registry.estimate_tokens(request).total_tokens < request.token_budget
    result = await service.assemble_prompt(request, require_registered=True)
    assert result.token_estimate > request.token_budget
    assert result.token_estimate >= registry.estimate_assembled_messages(result.messages)
    telemetry = result.metadata["consumer_token_telemetry"]
    assert telemetry["estimated_input_tokens"] == result.token_estimate
    assert telemetry["breakdown"]["system"] >= 5000
    assert result.messages[-1]["content"] == "query"


@pytest.mark.asyncio
async def test_registered_prompt_budget_includes_fixed_assembler_messages(tmp_path):
    from ai_karen_engine.core.runtime.prompt import PromptRegistry, PromptRuntimeService

    registry = PromptRegistry(tmp_path)
    service = PromptRuntimeService(registry=registry)
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "query"}],
        integrated_context={}, prompt_id="karen.agent.analyst.intent",
        prompt_version="v1.0.0", token_budget=4096,
    )
    result = await service.assemble_prompt(request, require_registered=True)
    assert result.token_estimate >= registry.estimate_assembled_messages(result.messages)
    assert result.metadata["context_policy"]["final_tokens"] == result.token_estimate
