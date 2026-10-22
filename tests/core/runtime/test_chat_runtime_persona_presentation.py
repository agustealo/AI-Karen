"""Authenticated persona selection is presentation-only at the canonical prompt boundary."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)


@pytest.mark.asyncio
async def test_runtime_uses_authenticated_persona_not_client_metadata():
    principal = SimpleNamespace(user_id="user-1", tenant_id="tenant-1")
    context = ChatExecutionContext(user_id="user-1", tenant_id="tenant-1")
    context.require_authenticated_user = lambda: principal
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        context=context,
        metadata={"persona": {"system_prompt": "untrusted", "tone": "hostile"}},
    )
    decision = SimpleNamespace(
        memory_recall_required=False, tool_requirements=[], workflow_id=None,
        workflow_version=None, requires_human_gate=False, requires_resumability=False,
        token_budget=2048,
    )
    service = SimpleNamespace(
        get_user_preferences=AsyncMock(return_value=SimpleNamespace(active_persona_id="verified")),
        get_persona=AsyncMock(return_value=SimpleNamespace(
            is_active=True, default_tone=SimpleNamespace(value="friendly"),
            default_verbosity=SimpleNamespace(value="balanced"),
            default_language=SimpleNamespace(value="en-US"),
        )),
    )
    assembler = SimpleNamespace(assemble_prompt=AsyncMock(return_value=SimpleNamespace(
        messages=[{"role": "system", "content": "safe"}],
        metadata={}, included_memory_refs=[],
    )))
    with patch("ai_karen_engine.services.persona.persona_service.get_persona_service", return_value=service), patch(
        "ai_karen_engine.core.runtime.prompt.get_prompt_runtime_service", return_value=assembler,
    ):
        await ChatRuntime._assemble_prompt_with_telemetry(
            SimpleNamespace(), request, decision,
        )
    offered = assembler.assemble_prompt.await_args.args[0]
    assert offered.persona == {"tone": "friendly", "verbosity": "balanced", "language_style": "en-US"}
    assert "system_prompt" not in offered.persona
    service.get_persona.assert_awaited_once_with("verified", "user-1", "tenant-1")
