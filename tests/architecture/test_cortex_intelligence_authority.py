from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def _text(relative: str) -> str:
    return (CORE / relative).read_text(encoding="utf-8")


def test_cortex_owns_global_cognitive_decision_boundary() -> None:
    cortex = _text("runtime/cortex_execution_decider.py")

    assert "class CortexExecutionDecider" in cortex
    assert "self._intelligence = get_intelligence_runtime()" in cortex
    assert "analysis = await self._analyze_request" in cortex
    assert "topology_triggers = self._evaluate_topology_triggers(analysis)" in cortex
    assert "risk_level = self._assess_risk_level(analysis)" in cortex
    assert "RuntimePolicyEnforcer" in cortex


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
