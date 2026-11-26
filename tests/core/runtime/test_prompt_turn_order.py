"""Canonical prompt ordering: internal context never follows the active user turn."""

import pytest
from types import SimpleNamespace

from ai_karen_engine.core.runtime.prompt.truncation_policy import HierarchicalTruncationPolicy

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



def _budget_estimate(request):
    """Deterministic token-cost fixture, not a provider tokenizer."""
    return SimpleNamespace(total_tokens=(
        sum(len(message["content"]) for message in request.messages)
        + sum(len(item["content"]) for item in request.memory_items)
    ))


def test_budget_trims_old_turn_without_orphaning_its_reply():
    messages = [
        {"role": "user", "content": "Old objective"},
        {"role": "assistant", "content": "Old unrelated reply"},
        {"role": "user", "content": "Make an original card game"},
        {"role": "assistant", "content": "Which theme?"},
        {"role": "user", "content": "Surprise me"},
    ]
    request = PromptAssemblyRequest(
        messages=list(messages),
        token_budget=sum(len(m["content"]) for m in messages[2:]),
    )
    events = HierarchicalTruncationPolicy().enforce(request, _budget_estimate)
    assert request.messages == messages[2:]
    assert len(events) == 1
    assert events[0].section == "history"
    assert events[0].items_removed == 2
    assert events[0].tokens_after <= request.token_budget


def test_budget_prefers_immediate_task_over_optional_memory():
    messages = [
        {"role": "user", "content": "Build a card game"},
        {"role": "assistant", "content": "Which kind?"},
        {"role": "user", "content": "Anything you choose"},
    ]
    request = PromptAssemblyRequest(
        messages=list(messages),
        memory_items=[{"content": "Unrelated memory " * 20}],
        token_budget=sum(len(m["content"]) for m in messages),
    )
    events = HierarchicalTruncationPolicy().enforce(request, _budget_estimate)
    assert request.messages == messages
    assert request.memory_items == []
    assert [event.section for event in events] == ["memory"]


def test_budget_drops_verbose_reply_before_immediate_user_objective():
    messages = [
        {"role": "user", "content": "Make a card game"},
        {"role": "assistant", "content": "Long explanation " * 50},
        {"role": "user", "content": "Surprise me"},
    ]
    request = PromptAssemblyRequest(
        messages=list(messages),
        token_budget=len(messages[0]["content"]) + len(messages[-1]["content"]),
    )
    events = HierarchicalTruncationPolicy().enforce(request, _budget_estimate)
    assert request.messages == [messages[0], messages[-1]]
    assert events[0].items_removed == 1
    assert _budget_estimate(request).total_tokens <= request.token_budget


def test_budget_can_drop_prior_anchor_but_never_active_user_or_attachment():
    attachment = {
        "role": "system", "content": "Verified attachment",
        "source": "verified_attachment_data",
    }
    active = {"role": "user", "content": "Continue"}
    request = PromptAssemblyRequest(
        messages=[
            {"role": "user", "content": "Previous objective"},
            {"role": "assistant", "content": "Previous answer"},
            attachment, active,
        ],
        token_budget=len(attachment["content"]) + len(active["content"]),
    )
    events = HierarchicalTruncationPolicy().enforce(request, _budget_estimate)
    assert request.messages == [attachment, active]
    assert sum(event.items_removed for event in events) == 2


def test_budget_never_detaches_protected_history_record():
    messages = [
        {"role": "user", "content": "Prior question"},
        {"role": "assistant", "content": "Verified attachment", "source": "verified_attachment_data"},
        {"role": "user", "content": "Continue"},
    ]
    request = PromptAssemblyRequest(messages=list(messages), token_budget=1)
    events = HierarchicalTruncationPolicy().enforce(request, _budget_estimate)
    assert request.messages == messages
    assert events == []
