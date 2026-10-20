"""Verified Medusa context must enter PromptRuntime, not tool authorization."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text()
PROMPT = (ROOT / "src/ai_karen_engine/core/runtime/prompt/prompt_assembler.py").read_text()
INGRESS = (ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py").read_text()


def test_verified_context_is_passed_to_canonical_prompt_runtime():
    assert '"verified_workspace_run": {' in RUNTIME
    assert 'request.metadata["verified_workspace_run"]["run_id"]' in RUNTIME
    assert 'request.metadata["verified_workspace_run"]["status"]' in RUNTIME
    assert "messages.append(self._build_workflow_message(request.workflow_context))" in PROMPT


def test_transport_verifies_before_runtime_and_does_not_grant_tool_authority():
    assert 'runtime_request.metadata["verified_workspace_run"] = verified' in INGRESS
    assert 'canonical_request.metadata["verified_workspace_run"] =' in INGRESS
    assert 'if request.tools or request.state or request.context:' in INGRESS
    assert 'Unsupported workspace context' in INGRESS

import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_prompt_context_is_bounded(monkeypatch):
    from ai_karen_engine.core.runtime import chat_runtime as runtime
    from ai_karen_engine.core.runtime import prompt
    observed = []
    class Finished(Exception):
        pass
    class Recorder:
        async def assemble_prompt(self, argument):
            observed.append(argument)
            raise Finished()
    monkeypatch.setattr(prompt, "get_prompt_runtime_service", lambda: Recorder())
    decision = SimpleNamespace(memory_recall_required=False, tool_requirements=[],
        workflow_id=None, workflow_version=None, requires_human_gate=False,
        requires_resumability=False, token_budget=512)
    request = SimpleNamespace(messages=[{"role":"user","content":"Explain"}],
        metadata={"verified_workspace_run":{"resource_type":"medusa_run",
            "run_id":"run-123","status":"running","extra_private":"hidden"}})
    with pytest.raises(Finished):
        await runtime.ChatRuntime._assemble_prompt_with_telemetry(
            object(), request, decision)
    context = observed[0].workflow_context["verified_workspace_run"]
    assert context["run_id"] == "run-123"
    assert "extra_private" not in context
    assert observed[0].tool_contracts == []


@pytest.mark.asyncio
async def test_non_medusa_context_never_reaches_prompt(monkeypatch):
    from ai_karen_engine.core.runtime import chat_runtime as runtime
    from ai_karen_engine.core.runtime import prompt
    observed = []
    class Finished(Exception):
        pass
    class Recorder:
        async def assemble_prompt(self, argument):
            observed.append(argument)
            raise Finished()
    monkeypatch.setattr(prompt, "get_prompt_runtime_service", lambda: Recorder())
    decision = SimpleNamespace(memory_recall_required=False, tool_requirements=[],
        workflow_id=None, workflow_version=None, requires_human_gate=False,
        requires_resumability=False, token_budget=512)
    request = SimpleNamespace(messages=[{"role":"user","content":"Explain"}],
        metadata={"verified_workspace_run":{"resource_type":"untrusted",
            "run_id":"other","status":"running"}})
    with pytest.raises(Finished):
        await runtime.ChatRuntime._assemble_prompt_with_telemetry(
            object(), request, decision)
    assert "verified_workspace_run" not in observed[0].workflow_context
