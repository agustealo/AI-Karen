"""Regression: LangGraph must not shadow canonical response-content policy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/formatting/response_formatter_pipeline.py"


def test_content_policy_is_shared_not_shadowed():
    source = PIPELINE.read_text(encoding="utf-8")
    assert "from ai_karen_engine.services.formatting.response_policy_enforcer import ResponsePolicyEnforcer" in source
    assert "class ResponsePolicyEnforcer:" not in source
    assert "self.policy_enforcer = ResponsePolicyEnforcer()" in source
    assert "await self.policy_enforcer.enforce(" in source
    assert "user_prompt=str(user_message)" in source
    assert "content=formatted_result.content" in source


def test_envelope_redaction_remains_distinct():
    source = PIPELINE.read_text(encoding="utf-8")
    assert "class ResponseEnvelopeSanitizer:" in source
    assert "self.envelope_sanitizer.enforce_policies(raw_response)" in source
    for name in ("internal_state", "raw_llm_response", "intermediate_steps"):
        assert name in source
