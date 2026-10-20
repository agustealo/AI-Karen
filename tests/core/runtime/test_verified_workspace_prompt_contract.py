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
