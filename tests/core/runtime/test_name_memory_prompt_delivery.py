"""Proof that an authorized profile fact reaches the canonical model prompt."""

import pytest

from ai_karen_engine.core.runtime.prompt import (
    PromptAssemblyRequest,
    get_prompt_runtime_service,
)


@pytest.mark.asyncio
async def test_personal_name_memory_reaches_model_prompt_without_conversation_history():
    fact = {
        "id": "profile-name-fact",
        "content": "name: Alex",
        "source_ref": "postgres_profile_fact",
    }
    assembled = await get_prompt_runtime_service().assemble_prompt(
        PromptAssemblyRequest(
            memory_items=[fact],
            messages=[{"role": "user", "content": "hats my name?"}],
            token_budget=4096,
        )
    )
    prompt_text = "\n".join(
        str(message.get("content") or "") for message in assembled.messages
    )
    assert "name: Alex" in prompt_text
    assert "hats my name?" in prompt_text
    assert "profile-name-fact" in assembled.provenance.memory_refs
