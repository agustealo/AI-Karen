"""Do not synthesize a Deep Agents primary result a second time."""

from __future__ import annotations

import pytest

from ai_karen_engine.agent_medusa.contracts.runtime_response import ResponseStatus
from ai_karen_engine.agent_medusa.response.assembler import ResponseAssembler


@pytest.mark.asyncio
async def test_single_deepagents_result_is_canonical_without_extra_model_call():
    result = await ResponseAssembler().assemble(
        request_id="run-1",
        step_outputs=[{
            "harness": "deepagents",
            "context_found": "Finished evidence-based research.",
            "tool_receipts": [{"receipt_id": "receipt-1"}],
        }],
        agent_trace=["researcher"],
        latest_user_message="Research a topic",
        status=ResponseStatus.SUCCESS,
        metadata={"policy_decision_id": "policy-1"},
    )
    assert result.content == "Finished evidence-based research."
    assert result.status == ResponseStatus.SUCCESS
    assert result.metadata["synthesis"]["additional_model_calls"] == 0
    assert result.metadata["policy_decision_id"] == "policy-1"
    assert result.intermediate_steps[0]["tool_receipts"][0]["receipt_id"] == "receipt-1"


@pytest.mark.asyncio
async def test_deepagents_missing_or_failed_result_cannot_fake_success():
    assembler = ResponseAssembler()
    with pytest.raises(ValueError, match="valid response"):
        await assembler.assemble(
            request_id="run-2",
            step_outputs=[{"harness": "deepagents", "context_found": ""}],
            agent_trace=["researcher"],
            latest_user_message="Research",
            status=ResponseStatus.SUCCESS,
        )
    failed = await assembler.assemble(
        request_id="run-3",
        step_outputs=[{"harness": "deepagents", "context_found": "interrupted"}],
        agent_trace=["researcher"],
        latest_user_message="Research",
        status=ResponseStatus.ERROR,
    )
    assert failed.status == ResponseStatus.ERROR
    assert failed.content != "interrupted"
