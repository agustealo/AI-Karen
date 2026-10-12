"""Response ownership audit guardrails against duplicated authorities."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/ai_karen_engine"


def test_canonical_runtime_is_both_chat_execution_entrypoints():
    transport = (SRC / "api_routes/chat/runtime.py").read_text(encoding="utf-8")
    assert "get_chat_runtime().execute(runtime_request)" in transport
    assert "get_chat_runtime().execute_stream(runtime_request)" in transport


def test_shared_formatter_has_single_public_facade():
    facade = (SRC / "services/formatting/response_formatting_engine.py").read_text(encoding="utf-8")
    assert "from ai_karen_engine.services.formatting.ResponseFormattingClass import" in facade
    engine = (SRC / "services/formatting/ResponseFormattingClass/Engine.py").read_text(encoding="utf-8")
    assert "class ResponseFormattingEngine(" in engine


def test_legacy_langgraph_policy_shadow_is_audited_before_convergence():
    pipeline = (SRC / "core/langgraph_orchestrator/formatting/response_formatter_pipeline.py").read_text(encoding="utf-8")
    # This is a characterization of current debt, not permission to preserve it.
    assert "class ResponsePolicyEnforcer:" in pipeline
    assert "from ai_karen_engine.services.formatting.response_policy_enforcer import ResponsePolicyEnforcer" in pipeline


def test_template_expansion_must_remain_disabled_by_default():
    policy = (SRC / "services/formatting/response_policy_enforcer.py").read_text(encoding="utf-8")
    assert "allow_template_fallback: bool = False" in policy


def test_grounded_response_guard_remains_in_both_runtime_modes():
    core = (SRC / "core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    assert core.count("grounded = self._grounded_personal_response(") >= 2
