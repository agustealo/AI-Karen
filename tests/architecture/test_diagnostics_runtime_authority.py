from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS = (
    ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/diagnostics.py"
)


def test_diagnostics_consumes_runtime_decision_pipeline_only() -> None:
    source = DIAGNOSTICS.read_text(encoding="utf-8")

    assert "RuntimeDecisionPipeline" in source
    assert "get_runtime_composition().decision_pipeline" in source
    assert "ChatExecutionRequest" in source

    forbidden = {
        "DecisionEngine",
        "LLMRouter",
        "select_provider(",
        "kari-fallback-v1",
        'or "default"',
        "DistilBertService",
    }
    found = sorted(token for token in forbidden if token in source)
    assert not found, (
        "Diagnostics must consume canonical Runtime/CORTEX truth without "
        f"shadow decision or provider authority: {found}"
    )


def test_diagnostics_fails_closed_on_missing_identity_scope() -> None:
    source = DIAGNOSTICS.read_text(encoding="utf-8")

    assert "Diagnostics requires explicit authenticated user_id" in source
    assert "Diagnostics requires explicit non-default tenant_id" in source
    assert '"predicted_provider": None' in source
    assert '"predicted_model": None' in source
