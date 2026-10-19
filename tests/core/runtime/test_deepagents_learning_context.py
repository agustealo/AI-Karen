"""Deep Agents consumes only CORTEX-authorized NeuroRecall via PromptRuntime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext, ContextEvidence, ContextRequirements,
    EvidenceScope, EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan, ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyResult
from ai_karen_engine.core.runtime.workflow_runtime import WorkflowRuntime


def request():
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Finish my research"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1",
            conversation_id="conv-1", request_id="req-1",
            correlation_id="corr-1",
        ),
    )


def plan():
    return AuthorizedExecutionPlan(
        execution_id="req-1", policy_decision_id="policy-1",
        authorized_tenant_id="tenant-1", authorized_user_id="user-1",
        authorized_session_id="session-1", topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"],
    )


def decision(*, source_allowed=True, other_tenant=False):
    requirements = ContextRequirements(
        request_id="req-1", correlation_id="corr-1",
        tenant_id="tenant-1", user_id="user-1",
        session_id="session-1", conversation_id="conv-1",
    )
    context = CognitiveContext(
        context_id="ctx-1", request_id="req-1", correlation_id="corr-1",
        tenant_id="tenant-1", user_id="user-1", requirements=requirements,
        policy_decision_id="policy-1",
        authorized_sources=["memory", "user_model"] if source_allowed else [],
        evidence=[
            ContextEvidence(
                evidence_id="memory-1", source=EvidenceSource.MEMORY,
                content="User prefers concise evidence-grounded reports.",
                scope=EvidenceScope(
                    tenant_id="other-tenant" if other_tenant else "tenant-1",
                    user_id="user-1", session_id="session-1",
                ),
            ),
            ContextEvidence(
                evidence_id="goal-1", source=EvidenceSource.USER_MODEL,
                content="Finish the current research before starting a new one.",
                scope=EvidenceScope(
                    tenant_id="tenant-1", user_id="user-1",
                    session_id="session-1",
                ),
            ),
        ],
    )
    return ExecutionDecision(
        topology=ExecutionTopology.MULTI_AGENT,
        requires_agent_delegation=True, memory_recall_required=True,
        intent="research", cognitive_context=context,
    )


@pytest.mark.asyncio
async def test_resolved_memory_is_assembled_by_existing_prompt_runtime_only(monkeypatch):
    from ai_karen_engine.core.runtime import prompt as prompt_module

    calls = []
    class PromptRuntime:
        async def assemble_prompt(self, assembly_request):
            calls.append(assembly_request)
            return PromptAssemblyResult(
                messages=[
                    {"role": "system", "content": "Authorized recalled context",
                     "source": "prompt-runtime"},
                    {"role": "user", "content": "Finish my research"},
                ],
                prompt_id=assembly_request.prompt_id,
                prompt_version=assembly_request.prompt_version,
                prompt_hash="approved-hash",
                included_memory_refs=["memory-1"],
            )
    monkeypatch.setattr(
        prompt_module, "get_prompt_runtime_service", lambda: PromptRuntime(),
    )
    messages, evidence = await WorkflowRuntime()._assemble_deepagents_learned_context(
        request(), decision(), plan(),
    )
    assert len(calls) == 1
    assert calls[0].prompt_id == "karen.chat.default"
    assert calls[0].memory_items[0]["id"] == "memory-1"
    assert calls[0].continuity_items[0]["id"] == "goal-1"
    assert messages == [
        {"role": "system", "content": "Authorized recalled context"},
        {"role": "user", "content": "Finish my research"},
    ]
    assert evidence["included_memory_count"] == 1
    assert "User prefers" not in str(evidence)


@pytest.mark.asyncio
async def test_denied_evidence_is_not_injected_into_prompt(monkeypatch):
    from ai_karen_engine.core.runtime import prompt as prompt_module
    captures = []

    async def assemble(req):
        captures.append(req)
        return PromptAssemblyResult(
            messages=req.messages, prompt_id=req.prompt_id,
            prompt_version=req.prompt_version, prompt_hash="hash",
        )
    monkeypatch.setattr(
        prompt_module, "get_prompt_runtime_service",
        lambda: SimpleNamespace(assemble_prompt=assemble),
    )
    _, status = await WorkflowRuntime()._assemble_deepagents_learned_context(
        request(), decision(source_allowed=False), plan(),
    )
    assert captures[0].memory_items == []
    assert captures[0].continuity_items == []
    assert status["included_memory_count"] == 0


@pytest.mark.asyncio
async def test_cross_tenant_resolved_memory_is_rejected_before_prompt(monkeypatch):
    from ai_karen_engine.core.runtime import prompt as prompt_module
    async def must_not_assemble(_request):
        raise AssertionError("cross-tenant memory crossed PromptRuntime")
    monkeypatch.setattr(
        prompt_module, "get_prompt_runtime_service",
        lambda: SimpleNamespace(assemble_prompt=must_not_assemble),
    )
    with pytest.raises(PermissionError, match="crosses authorized scope"):
        await WorkflowRuntime()._assemble_deepagents_learned_context(
            request(), decision(other_tenant=True), plan(),
        )


@pytest.mark.asyncio
async def test_wrong_cortex_or_policy_context_fails_closed():
    decision_instance = decision()
    decision_instance.cognitive_context.correlation_id = "other-run"
    with pytest.raises(PermissionError, match="scope mismatch"):
        await WorkflowRuntime()._assemble_deepagents_learned_context(
            request(), decision_instance, plan(),
        )


@pytest.mark.asyncio
async def test_cold_start_does_not_fabricate_recalled_user_facts():
    execution = ExecutionDecision(
        topology=ExecutionTopology.MULTI_AGENT,
        memory_recall_required=True, cognitive_context=None,
    )
    messages, status = await WorkflowRuntime()._assemble_deepagents_learned_context(
        request(), execution, plan(),
    )
    assert messages is None
    assert status == {"status": "unavailable", "included_memory_count": 0}
