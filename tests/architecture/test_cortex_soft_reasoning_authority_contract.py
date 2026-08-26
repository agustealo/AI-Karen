"""Architecture proofs for CORTEX authority and Soft Reasoning research truth."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"
CORE = SRC / "core"
CORTEX_CONTRACTS = CORE / "cortex" / "contracts.py"
CORTEX_DISPATCH = CORE / "cortex" / "dispatch.py"
RUNTIME_DECISION = CORE / "runtime" / "execution_decision.py"
RUNTIME_DECIDER = CORE / "runtime" / "cortex_execution_decider.py"
SOFT_ROOT = CORE / "reasoning" / "soft_reasoning"
SOFT_INIT = SOFT_ROOT / "__init__.py"
SOFT_CONTRACTS = SOFT_ROOT / "contracts.py"
SOFT_EXPLORATION = SOFT_ROOT / "exploration.py"
SOFT_OPTIMIZATION = SOFT_ROOT / "optimization.py"
SOFT_OBJECTIVE = SOFT_ROOT / "objective.py"
SOFT_STRATEGY = CORE / "reasoning" / "strategies" / "soft_strategy.py"
REASONING_DEFAULTS = CORE / "reasoning" / "defaults.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _class_defaults(path: Path, class_name: str) -> dict[str, object]:
    tree = ast.parse(_source(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        defaults: dict[str, object] = {}
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            if item.value is None:
                continue
            try:
                defaults[item.target.id] = ast.literal_eval(item.value)
            except (ValueError, TypeError):
                continue
        return defaults
    raise AssertionError(f"class not found: {class_name}")


def test_cortex_routing_contract_is_advisory_and_memory_write_fails_closed() -> None:
    source = _source(CORTEX_CONTRACTS)
    defaults = _class_defaults(CORTEX_CONTRACTS, "RoutingDecision")

    assert "This contract is advisory, not an authorization grant" in source
    assert defaults["allow_memory_write"] is False
    assert defaults["target_graph"] is None


def test_legacy_cortex_dispatch_does_not_blanket_route_chat_to_langgraph() -> None:
    source = _source(CORTEX_DISPATCH)
    routing = source.split("def _build_routing_decision", 1)[1].split(
        "def _build_cortex_output", 1
    )[0]

    assert "compatibility surface" in source.lower()
    assert "graph_semantics" in routing
    assert "ExecutionMode.DIRECT" in routing
    assert "allow_memory_write=False" in routing
    assert "else ExecutionMode.LANGGRAPH" not in routing
    assert 'target_graph = "default_chat_graph"' not in routing


def test_legacy_cortex_protected_routes_fail_closed_without_rbac() -> None:
    source = _source(CORTEX_DISPATCH)
    evaluation = source.split("async def evaluate_cortex", 1)[1].split(
        "def _normalize", 1
    )[0]

    assert "rbac_unavailable_fail_closed" in evaluation
    assert "requires RBAC validation but the validator is unavailable" in evaluation
    assert "routing permission checks disabled" not in source


def test_execution_decision_keeps_reasoning_modes_separate_from_capabilities() -> None:
    source = _source(RUNTIME_DECISION)
    defaults = _class_defaults(RUNTIME_DECISION, "ExecutionDecision")

    assert "reasoning_modes: List[str]" in source
    assert "required_capabilities: List[str]" in source
    assert defaults["memory_write_allowed"] is False
    assert "Capability and\n    reasoning-mode domains are intentionally distinct" in source


def test_live_cortex_requires_explicit_memory_write_recommendation_and_policy_grant() -> None:
    source = _source(RUNTIME_DECIDER)

    assert 'analysis.get("memory_write_requested", False)' in source
    assert 'meta.get("memory_write_requested", False)' in source
    assert 'analysis.get("memory_write_denied", False)' in source
    assert 'requested_capabilities.append("memory.write")' in source
    assert 'memory_write_requested and "memory.write" in required_capabilities' in source
    assert '"memory_write_requested": memory_write_requested' in source
    assert '"memory_write_authorized": memory_write_allowed' in source


def test_live_cortex_has_typed_reasoning_mode_signal() -> None:
    source = _source(RUNTIME_DECIDER)

    assert "def _normalize_reasoning_modes" in source
    assert 'reasoning_modes=["causal", "verify", "refine", "metacognition"]' not in source
    assert 'reasoning_modes = ["causal", "verify", "refine", "metacognition"]' in source
    assert "reasoning_modes=reasoning_modes" in source


def test_soft_reasoning_package_does_not_claim_default_paper_fidelity() -> None:
    source = _source(SOFT_INIT)

    assert "Do not describe the" in source
    assert "paper-faithful reproduction" in source
    assert "true Gaussian-process posterior" in source
    assert "sequence-coherence/log-probability" in source


def test_soft_optimizer_reports_kernel_regression_instead_of_fake_gp() -> None:
    source = _source(SOFT_OPTIMIZATION)

    assert 'surrogate_kind = "kernel_regression"' in source
    assert "This is not a full Gaussian Process implementation" in source
    assert "def _surrogate_predict" in source
    assert "def _gp_predict" in source  # compatibility alias only
    alias = source.split("def _gp_predict", 1)[1].split("def _rbf_kernel", 1)[0]
    assert "return self._surrogate_predict(embedding)" in alias


def test_soft_generation_contract_types_paper_coherence_signals() -> None:
    source = _source(SOFT_CONTRACTS)

    assert "sequence_log_probability: float | None" in source
    assert "mean_token_log_probability: float | None" in source
    assert "first_token_probability: float | None" in source
    assert "optimizer_surrogate_kind: str" in source
    assert "acquisition_function: str" in source
    assert "research_profile: str" in source


def test_soft_exploration_exposes_actual_research_profile() -> None:
    source = _source(SOFT_EXPLORATION)

    assert 'research_profile: str = "karen_default"' in source
    assert "optimizer_surrogate_kind=optimization.surrogate_kind" in source
    assert "acquisition_function=self._config.acquisition.value" in source
    assert "research_profile=self._config.research_profile" in source


def test_karen_soft_objective_is_not_mislabeled_as_paper_reward() -> None:
    source = _source(SOFT_OBJECTIVE)

    assert 'objective_kind = "karen_structured_verifier"' in source
    assert "implements\nKAREN's richer verifier objective only" in source
    assert "sequence-coherence/log-probability" in source


def test_soft_strategy_reports_research_fidelity_in_diagnostics() -> None:
    source = _source(SOFT_STRATEGY)

    assert '"research_fidelity"' in source
    assert 'trace.optimizer_surrogate_kind == "gaussian_process"' in source
    assert 'trace.acquisition_function == "ei"' in source
    assert 'else "research_aligned"' in source
    assert '"sequence_log_probability"' in source


def test_soft_reasoning_is_not_implicitly_bootstrapped_by_core_defaults() -> None:
    source = _source(REASONING_DEFAULTS)

    assert "SoftReasoner(" not in source
    assert "optional_strategies" in source
    assert "Runtime injects a configured" in source
