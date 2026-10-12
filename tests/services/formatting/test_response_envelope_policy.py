"""Behavioral tests for separate envelope cleanup and text policy."""
from ai_karen_engine.services.formatting.response_envelope_policy import ResponseEnvelopePolicy


def test_envelope_policy_redacts_internal_fields_and_preserves_public_data():
    policy = ResponseEnvelopePolicy()
    result = policy.enforce_policies({
        "content": "Safe factual reply",
        "internal_state": {"secret": "do not expose"},
        "raw_llm_response": "private",
        "tool_results": {"count": 1},
    })
    assert result == {
        "content": "Safe factual reply",
        "tool_results": {"count": 1},
        "response": "Safe factual reply",
    }


def test_envelope_policy_retains_explicit_response_and_caps_length():
    policy = ResponseEnvelopePolicy()
    result = policy.enforce_policies({
        "response": "x" * 100001,
        "content": "do not replace explicitly provided response",
    })
    assert result["response"] == ("x" * 100000) + "... (truncated)"
    assert result["content"] == "do not replace explicitly provided response"


def test_empty_response_is_not_replaced_by_content():
    result = ResponseEnvelopePolicy().enforce_policies({
        "response": "",
        "content": "different",
    })
    assert result["response"] == ""


def test_response_policy_names_are_not_shadowed_in_langgraph():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "src/ai_karen_engine/core/langgraph_orchestrator/formatting/response_formatter_pipeline.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "class ResponsePolicyEnforcer:" not in source
    assert "self.policy_enforcer.enforce(" in source
    assert "content=formatted_result.content" in source
