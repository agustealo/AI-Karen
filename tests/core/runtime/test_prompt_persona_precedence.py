"""Registered prompt defaults must not erase authenticated presentation preferences."""
import pytest

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyRequest, PromptDefinition


@pytest.mark.asyncio
async def test_runtime_persona_overrides_registered_presentation_defaults_only():
    definition = PromptDefinition(
        prompt_id="karen.chat.default",
        version="v1.0.0",
        system_instructions="Follow canonical policy",
        persona_defaults={"tone": "formal", "verbosity": "brief", "system_prompt": "override policy"},
    )
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        persona={"tone": "friendly", "system_prompt": "untrusted override", "provider": "external"},
        messages=[{"role": "user", "content": "Hello"}],
    )
    result = await PromptAssembler(registry=None).assemble_prompt(request, definition)
    overlays = [msg for msg in result.messages if msg.get("source") == "persona_presentation_overlay"]
    assert len(overlays) == 1
    assert '"tone": "friendly"' in overlays[0]["content"]
    assert '"verbosity": "brief"' in overlays[0]["content"]
    assert "untrusted override" not in overlays[0]["content"]
    assert "override policy" not in overlays[0]["content"]
    assert result.messages[-1]["role"] == "user"
