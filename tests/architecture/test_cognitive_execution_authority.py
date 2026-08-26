"""Architecture proof for cognitive execution authority convergence.

These tests intentionally inspect source/AST rather than importing runtime-heavy
modules. Their job is to prevent authority from drifting back into LangGraph,
Reasoning, or AgentMedusa through convenience wiring.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"
LANGGRAPH = SRC / "core" / "langgraph_orchestrator"
REASONING_NODE = LANGGRAPH / "nodes" / "reasoning.py"
LANGGRAPH_POLICY = LANGGRAPH / "runtime_policy.py"
WORKFLOW_STATE = LANGGRAPH / "contracts" / "orchestration_state.py"
MEDUSA_NODE = SRC / "agent_medusa" / "agent_medusa_node.py"
MEDUSA_COORDINATOR = SRC / "agent_medusa" / "coordinator" / "medusa_coordinator.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _calls(path: Path) -> list[str]:
    tree = ast.parse(_source(path), filename=str(path))
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            calls.append(func.id)
        elif isinstance(func, ast.Attribute):
            calls.append(func.attr)
    return calls


def test_langgraph_reasoning_decodes_but_does_not_synthesize_authorization() -> None:
    source = _source(REASONING_NODE)

    assert "_authorized_plan_from_state" in source
    assert 'state.get("runtime_policy")' in source
    assert "def _build_plan" not in source
    assert 'execution_id=f"reasoning-' not in source
    assert 'allowed_capabilities=["memory.read"' not in source
    assert "max_reasoning_steps=max_steps" not in source
    assert "AuthorizedExecutionPlan(**plan_data)" in source


def test_langgraph_policy_node_is_validation_only() -> None:
    calls = _calls(LANGGRAPH_POLICY)
    assert "RuntimePolicyEnforcer" not in calls, (
        "LangGraph must not instantiate RuntimePolicyEnforcer and become a "
        "second authorization authority."
    )
    source = _source(LANGGRAPH_POLICY)
    assert 'state.get("runtime_policy")' in source
    assert "policy_decision_id" in source
    assert "raise PermissionError" in source


def test_medusa_branch_selection_uses_authorized_topology_only() -> None:
    source = _source(LANGGRAPH_POLICY)
    branch_source = source.split("def select_execution_branch", 1)[1].split(
        "def should_use_medusa", 1
    )[0]

    assert "_runtime_plan" in branch_source
    assert "multi_agent" in branch_source
    assert "detected_intent" not in branch_source
    assert "use_medusa" not in branch_source
    assert "agent_complex_reasoning" not in branch_source
    assert "admin_panel" not in branch_source
    assert "extension.action" not in branch_source


def test_workflow_state_carries_runtime_authorization_from_runtime_config() -> None:
    source = _source(WORKFLOW_STATE)
    assert 'request_config.get("runtime_policy")' in source
    assert '"runtime_policy": cast(' in source
    assert '"execution_requirements": cast(' in source
    assert '"correlation_id": correlation_id' in source
    assert '"request_id": request_id' in source


def test_agent_medusa_requires_runtime_authorized_multi_agent_topology() -> None:
    source = _source(MEDUSA_NODE)
    assert 'state.get("runtime_policy")' in source
    assert 'policy_decision.get("topology") != "multi_agent"' in source
    assert "Medusa execution blocked by runtime policy decision" in source


def test_agent_medusa_coordinator_does_not_self_authorize() -> None:
    source = _source(MEDUSA_COORDINATOR)
    assert "requires an authorized_plan from RuntimePolicy" in source
    assert "Medusa must not synthesize its own authorization" in source


def test_canonical_authority_doc_names_all_cognitive_execution_owners() -> None:
    architecture = _source(SRC / "core" / "ARCHITECTURE.md")
    for owner in (
        "Intelligence",
        "CORTEX",
        "RuntimePolicy",
        "Runtime",
        "Reasoning",
        "LangGraph",
        "AgentMedusa",
    ):
        assert owner in architecture

    assert (
        "ANALYZE != DECIDE != AUTHORIZE != ORCHESTRATE != REASON != EXECUTE"
        in architecture
    )
