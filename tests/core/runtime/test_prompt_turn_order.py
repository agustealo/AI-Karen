"""Canonical prompt ordering: internal context never follows the active user turn."""

import pytest

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyRequest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["Hello", "Only said hello!", "I'm from Jamaica though", "I'm Zeus"],
)
async def test_active_user_turn_remains_last_after_runtime_context(text: str) -> None:
    assembler = PromptAssembler(registry=None)
    result = await assembler.assemble_prompt(
        PromptAssemblyRequest(
            messages=[{"role": "user", "content": text}],
            workflow_context={"workflow_id": "run-1", "requires_human_gate": False},
            provider_capabilities={"streaming": True},
            tool_contracts=[{"name": "search", "description": "Authorized only"}],
        )
    )

    assert result.messages[-1] == {"role": "user", "content": text}
    assert result.messages[-2]["source"] == "provider_capabilities"
    assert any(message.get("source") == "workflow_context" for message in result.messages)
    assert any(message.get("source") == "tool_contract_0" for message in result.messages)


@pytest.mark.asyncio
async def test_existing_conversation_sequence_is_preserved() -> None:
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "I'm Zeus"},
    ]
    result = await PromptAssembler(registry=None).assemble_prompt(
        PromptAssemblyRequest(messages=messages, workflow_context={"workflow_id": "wf"})
    )

    assert result.messages[-len(messages):] == messages


@pytest.mark.asyncio
async def test_personal_followup_prompt_prioritizes_new_turn_not_replayed_biography() -> None:
    messages = [
        {"role": "user", "content": "What can you tell me about myself?"},
        {"role": "assistant", "content": "You grew up in NYC."},
        {"role": "user", "content": "Anything else?"},
        {"role": "assistant", "content": "Your favorite color is black."},
        {"role": "user", "content": "I am a vegetarian, and dancehall is my favorite genre."},
    ]
    result = await PromptAssembler(registry=None).assemble_prompt(
        PromptAssemblyRequest(
            messages=messages,
            memory_items=[{
                "id": "owned-profile-name",
                "content": "name: Zeus",
            }],
        )
    )
    assert result.messages[-len(messages):] == messages
    instructions = [
        str(message.get("content") or "") for message in result.messages
        if message.get("source") == "evidence_first_conversation_contract"
    ]
    assert len(instructions) == 1
    assert "do not repeat the same biography" in instructions[0]
    assert "acknowledge the new fact directly" in instructions[0]
    assert "Prior assistant answers are discourse context" in instructions[0]
