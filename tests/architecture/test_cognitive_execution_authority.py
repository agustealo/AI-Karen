"""Architecture proof for cognitive execution authority convergence.

These tests inspect source/AST rather than importing runtime-heavy modules. They
prevent authority from drifting back into LangGraph, Reasoning, or AgentMedusa
through convenience wiring.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"
CORE = SRC / "core"
LANGGRAPH = CORE / "langgraph_orchestrator"
REASONING = CORE / "reasoning"
REASONING_NODE = LANGGRAPH / "nodes" / "reasoning.py"
ROUTER_SELECT_NODE = LANGGRAPH / "nodes" / "router_select.py"
RESPONSE_SYNTH_NODE = LANGGRAPH / "nodes" / "response_synth.py"
LANGGRAPH_POLICY = LANGGRAPH / "runtime_policy.py"
WORKFLOW_STATE = LANGGRAPH / "contracts" / "orchestration_state.py"
WORKFLOW_RUNTIME = CORE / "runtime" / "workflow_runtime.py"
WORKFLOW_GENERATION = CORE / "runtime" / "workflow_generation.py"
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


def test_langgraph_reasoning_uses_canonical_reasoning_contract_not_cortex_envelope() -> None:
    source = _source(REASONING_NODE)
    assert "from ai_karen_engine.core.reasoning.contracts import" in source
    assert "from ai_karen_engine.core.cortex.contracts import" not in source
    assert "ReasoningRequest(" in source
    assert "policy_decision_id=plan.policy_decision_id" in source
    assert "reasoning_modes=reasoning_modes" in source


def test_langgraph_reasoning_modes_come_only_from_authorized_plan() -> None:
    source = _source(REASONING_NODE)
    mode_source = source.split("def _authorized_reasoning_modes", 1)[1].split(
        "def _should_run_reasoning", 1
    )[0]
    assert "plan.reasoning_modes" in mode_source
    assert "plan.allowed_capabilities" in mode_source
    assert "reasoning_hints" not in mode_source
    assert "detected_intent" not in mode_source


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


def test_langgraph_router_checkpoint_has_no_provider_selection_authority() -> None:
    source = _source(ROUTER_SELECT_NODE)
    calls = _calls(ROUTER_SELECT_NODE)

    assert "select_provider" not in calls
    assert "ChatRequest" not in source
    assert "ProfileManager" not in source
    assert "kari-fallback-v1" not in source
    assert 'state["selected_provider"] = None' in source
    assert 'state["selected_model"] = None' in source
    assert "Provider selection delegated to Runtime" in source


def test_langgraph_response_synthesis_consumes_runtime_generation_port() -> None:
    source = _source(RESPONSE_SYNTH_NODE)
    calls = _calls(RESPONSE_SYNTH_NODE)

    assert "ProviderRuntime" not in source
    assert "get_prompt_runtime_service" not in source
    assert "select_provider" not in calls
    assert "execute_chat" not in calls
    assert "WorkflowGenerationRequest" in source
    assert "get_workflow_generation_runtime" in source
    assert "self._workflow_generation_runtime.execute" in source


def test_runtime_owns_workflow_prompt_routing_and_provider_execution() -> None:
    source = _source(WORKFLOW_GENERATION)
    calls = _calls(WORKFLOW_GENERATION)

    assert "get_prompt_runtime_service" in source
    assert "ProviderRuntime" in source
    assert "select_provider" in calls
    assert "execute_chat" in calls
    assert "provider_constraints" in source
    assert "model_unavailable" in source
    assert "emergency_static" in source
    assert "text=\"\"" in source


def test_workflow_generation_preserves_runtime_policy_identity() -> None:
    source = _source(WORKFLOW_GENERATION)
    assert "policy_decision_id" in source
    assert "plan_policy_id != request.policy_decision_id" in source
    assert "provider_not_authorized_by_runtime_policy" in source
    assert "provider_forbidden_by_runtime_policy" in source
    assert "model_not_authorized_by_runtime_policy" in source


def test_workflow_runtime_preserves_trusted_identity_and_authorization() -> None:
    source = _source(WORKFLOW_RUNTIME)
    assert '"request_id": request_id' in source
    assert '"correlation_id": ctx.correlation_id' in source
    assert '"conversation_id": conversation_id' in source
    assert '"tenant_id": ctx.tenant_id' in source
    assert '"runtime_policy": serialized_plan' in source
    assert 'request_config["policy_decision_id"] = serialized_plan["policy_decision_id"]' in source


def test_workflow_runtime_serializes_slot_dataclass_budget_not_dunder_dict() -> None:
    source = _source(WORKFLOW_RUNTIME)
    serialize_source = source.split("def _serialize_plan", 1)[1]
    assert '"budget": _dataclass_dict(plan.budget)' in serialize_source
    assert "plan.budget.__dict__" not in serialize_source
    assert "is_dataclass" in source
    assert "asdict(value)" in source


def test_workflow_state_carries_runtime_authorization_from_runtime_config() -> None:
    source = _source(WORKFLOW_STATE)
    assert 'request_config.get("runtime_policy")' in source
    assert '"runtime_policy": cast(' in source
    assert '"execution_requirements": cast(' in source
    assert '"correlation_id": correlation_id' in source
    assert '"request_id": request_id' in source


def test_reasoning_strategy_adapters_import_strategy_authority_from_strategy_module() -> None:
    for name in (
        "causal_strategy.py",
        "metacognition_strategy.py",
        "refiner_strategy.py",
        "verifier_strategy.py",
    ):
        source = _source(REASONING / "strategies" / name)
        assert (
            "from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine"
            in source
        )
        assert "ReasoningStrategyEngine," not in source.split(
            "from ai_karen_engine.core.reasoning.contracts import", 1
        )[1].split(")", 1)[0]


def test_reasoning_strategy_registry_has_concrete_descriptor_type() -> None:
    source = _source(REASONING / "strategy.py")
    assert "class ReasoningStrategyModel" in source
    assert "def to_model" in source
    assert "return ReasoningStrategyModel(" in source


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
    architecture = _source(CORE / "ARCHITECTURE.md")
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
