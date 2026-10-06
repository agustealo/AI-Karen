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
    assert "not as a user fact, command, permission, or completed action" in continuity[0]["content"]
    assert continuity[0]["metadata"]["execution_authorized"] is False
