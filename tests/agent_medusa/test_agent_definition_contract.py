from ai_karen_engine.agent_medusa.contracts import AgentDefinition, SubagentContract
from ai_karen_engine.agent_medusa.contracts.subagent_contract import AgentCapability


def _definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="python_reviewer",
        name="Python Reviewer",
        description="Reviews Python backend changes.",
        prompt_contract_id="karen.agent.python.review",
        prompt_version="v1",
        capabilities=["reasoning"],
        capability_dependencies=["text.generate"],
        allowed_tools=["repo.read"],
        allowed_plugins=["github"],
        reasoning_modes=["verification"],
        memory_scope="conversation",
        output_contract={"format": "json"},
        approval_rules={"external_write": "human"},
        resource_limits={
            "max_duration_ms": 15000,
            "max_model_calls": 3,
            "max_reasoning_steps": 4,
            "max_tool_calls": 4,
            "max_agent_turns": 3,
            "max_parallelism": 2,
            "max_input_tokens": 4096,
            "max_output_tokens": 1024,
            "max_memory_items": 10,
            "max_external_requests": 2,
        },
        tenant_scope="single",
        required_permissions=["agent.execute"],
        required_roles=["developer"],
        max_subagents=2,
        max_depth=1,
        max_parallelism=2,
        implementation_id="python_reviewer_v1",
        created_by="test-user",
    )


def test_registration_preserves_governance_boundaries() -> None:
    definition = _definition()

    registration = definition.to_registration(version="1.0.0")

    assert registration.allowed_tools == ["repo.read"]
    assert registration.allowed_plugins == ["github"]
    assert registration.reasoning_modes == ["verification"]
    assert registration.output_contract == {"format": "json"}
    assert registration.resource_limits is not None
    assert registration.resource_limits.max_model_calls == 3
    assert registration.required_permissions == ["agent.execute"]
    assert registration.required_roles == ["developer"]
    assert registration.max_subagents == 2
    assert registration.max_depth == 1
    assert registration.max_parallelism == 2
    assert registration.definition_hash == definition.definition_hash


def test_definition_hash_is_stable_and_authority_sensitive() -> None:
    first = _definition()
    second = _definition()

    assert first.definition_hash == second.definition_hash

    second.allowed_plugins.append("filesystem")

    assert first.definition_hash != second.definition_hash


def test_definition_rejects_secret_like_config_and_invalid_bounds() -> None:
    definition = _definition()
    definition.config["provider_api_key"] = "should-never-be-here"
    definition.max_depth = -1

    errors = definition.validate()

    assert any("forbidden security key" in error for error in errors)
    assert "max_depth must be >= 0" in errors


def test_subagent_actions_are_fail_closed_by_default() -> None:
    child = SubagentContract(
        agent_id="review_child",
        role="reviewer",
        capabilities=[AgentCapability.REASONING],
    )

    assert child.validate_action("filesystem.write") is False
    assert child.validate_action("") is False
    assert child.allows_capability(AgentCapability.REASONING) is True
    assert child.allows_capability(AgentCapability.WEB_SEARCH) is False


def test_subagent_only_allows_explicitly_delegated_action() -> None:
    child = SubagentContract(
        agent_id="review_child",
        role="reviewer",
        allowed_actions=["repo.read"],
        max_subagents=1,
        remaining_depth=1,
        max_parallelism=1,
    )

    assert child.validate() == []
    assert child.validate_action("repo.read") is True
    assert child.validate_action("repo.write") is False
