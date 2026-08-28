from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def _text(relative: str) -> str:
    return (CORE / relative).read_text(encoding="utf-8")


def test_cortex_owns_global_cognitive_decision_boundary() -> None:
    cortex = _text("cortex/executive.py")

    assert "class CortexExecutionDecider" in cortex
    assert "self._intelligence = get_intelligence_runtime()" in cortex
    assert "analysis = await self._analyze_request" in cortex
    assert "topology_triggers = self._evaluate_topology_triggers(analysis)" in cortex
    assert "risk_level = self._assess_risk_level(analysis)" in cortex

    # CORTEX decides only. Authorization belongs to RuntimePolicy in the
    # Runtime-owned decision pipeline, never inside the cognitive executive.
    assert "RuntimePolicyEnforcer" not in cortex
    assert "ExpressionGateway" not in cortex
    assert "WorkflowRuntime" not in cortex


def test_runtime_pipeline_owns_policy_authorization_after_cortex() -> None:
    pipeline = _text("runtime/decision_pipeline.py")

    assert "class RuntimeDecisionPipeline" in pipeline
    assert "preliminary = await self._cortex.decide(request)" in pipeline
    assert "policy = await self._evaluate_execution_policy(request, cognitive)" in pipeline
    assert "return self._apply_execution_policy(cognitive, policy)" in pipeline
    assert "RuntimePolicyEnforcer" in pipeline


def test_intelligence_is_analysis_capability_not_execution_authority() -> None:
    intelligence_root = CORE / "intelligence"
    assert intelligence_root.exists()

    forbidden = (
        "ProviderRuntime(",
        "LLMRouter(",
        "RuntimePolicyEnforcer(",
        "WorkflowRuntime(",
        "LangGraphOrchestrator(",
    )

    offenders: list[str] = []
    for path in intelligence_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")

    assert not offenders, "Intelligence crossed its analysis boundary:\n" + "\n".join(offenders)


def test_architecture_names_cortex_as_global_cognitive_decision_owner() -> None:
    architecture = _text("ARCHITECTURE.md")

    assert "CORTEX is the only global cognitive decision owner" in architecture
    assert "cortex/                  GLOBAL DECISION AUTHORITY" in architecture
    assert "intelligence/            ANALYSIS / ML SIGNALS" in architecture
