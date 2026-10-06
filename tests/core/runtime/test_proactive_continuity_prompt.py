from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyRequest
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry


@pytest.mark.asyncio
async def test_continuity_candidates_are_labeled_non_authoritative() -> None:
    assembler = PromptAssembler(PromptRegistry())
    result = await assembler.assemble_prompt(
        PromptAssemblyRequest(
            continuity_items=[
                {
                    "id": "next-1",
                    "subject": "send the client the revised estimate",
                    "source_type": "open_loop",
                    "source_id": "open-1",
                    "utility": 0.8,
                    "confidence": 0.95,
                    "urgency": "normal",
                    "reason_codes": ["unfinished_work"],
                }
            ],
            messages=[{"role": "user", "content": "What should I do next?"}],
        )
    )

    continuity = [
        message
        for message in result.messages
        if str(message.get("source", "")).startswith("proactive_continuity_")
    ]
    assert len(continuity) == 1
    assert "possible next need" in continuity[0]["content"]
    assert (
        "not as a user fact, command, permission, or completed action"
        in continuity[0]["content"]
    )
    assert continuity[0]["metadata"]["execution_authorized"] is False


@pytest.mark.asyncio
async def test_clear_primary_continuity_can_anchor_explicit_resume() -> None:
    assembler = PromptAssembler(PromptRegistry())
    result = await assembler.assemble_prompt(
        PromptAssemblyRequest(
            continuity_items=[
                {
                    "id": "next-1",
                    "subject": "finish the client estimate",
                    "source_type": "open_loop",
                    "source_id": "open-1",
                    "utility": 0.86,
                    "confidence": 0.96,
                    "urgency": "normal",
                    "reason_codes": ["unfinished_work"],
                    "resume_primary": True,
                    "resume_ambiguous": False,
                }
            ],
            messages=[{"role": "user", "content": "Continue."}],
        )
    )

    continuity = [
        message
        for message in result.messages
        if str(message.get("source", "")).startswith("proactive_continuity_")
    ]
    assert len(continuity) == 1
    assert "clear primary unfinished thread" in continuity[0]["content"]
    assert continuity[0]["metadata"]["resume_primary"] is True
    assert continuity[0]["metadata"]["execution_authorized"] is False


@pytest.mark.asyncio
async def test_ambiguous_resume_requires_choices_not_guessing() -> None:
    assembler = PromptAssembler(PromptRegistry())
    result = await assembler.assemble_prompt(
        PromptAssemblyRequest(
            continuity_items=[
                {
                    "id": "next-1",
                    "subject": "finish the client estimate",
                    "source_type": "open_loop",
                    "source_id": "open-1",
                    "utility": 0.72,
                    "confidence": 0.95,
                    "urgency": "normal",
                    "reason_codes": ["unfinished_work"],
                    "resume_primary": False,
                    "resume_ambiguous": True,
                },
                {
                    "id": "next-2",
                    "subject": "book the hotel",
                    "source_type": "open_loop",
                    "source_id": "open-2",
                    "utility": 0.70,
                    "confidence": 0.94,
                    "urgency": "normal",
                    "reason_codes": ["unfinished_work"],
                    "resume_primary": False,
                    "resume_ambiguous": True,
                },
            ],
            messages=[{"role": "user", "content": "Continue."}],
        )
    )

    continuity = [
        message
        for message in result.messages
        if str(message.get("source", "")).startswith("proactive_continuity_")
    ]
    assert len(continuity) == 2
    assert all("Do not guess which one the user means" in item["content"] for item in continuity)
    assert all(item["metadata"]["resume_ambiguous"] is True for item in continuity)
