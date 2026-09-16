from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_GATE = (
    ROOT
    / "src/ai_karen_engine/core/langgraph_orchestrator/nodes/auth_gate.py"
)
WORKFLOW_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/workflow_runtime.py"
LANGGRAPH_ORCHESTRATOR = (
    ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
)


def _class_method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == method_name:
                    segment = ast.get_source_segment(source, member)
                    assert segment is not None
                    return segment
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


def test_langgraph_auth_gate_consumes_runtime_identity_only() -> None:
    gate_source = _class_method_source(AUTH_GATE, "AuthGateNode", "__call__")

    assert 'state.get("auth_context")' in gate_source
    assert 'auth_context.get("user_id")' in gate_source
    assert 'auth_context.get("tenant_id")' in gate_source
    assert 'state["auth_status"] = "authenticated"' in gate_source

    # LangGraph must never become a second authentication or tenant authority.
    assert "get_auth_service" not in gate_source
    assert "validate_token" not in gate_source
    assert "verify_token" not in gate_source
    assert "get_user" not in gate_source
    assert "allow_anonymous" not in gate_source
    assert 'or "default"' not in gate_source


def test_langgraph_auth_gate_fails_closed_on_identity_or_tenant_mismatch() -> None:
    gate_source = _class_method_source(AUTH_GATE, "AuthGateNode", "__call__")

    assert "Runtime user identity mismatch" in gate_source
    assert "Runtime tenant identity mismatch" in gate_source
    assert "Trusted Runtime identity is incomplete" in gate_source
    assert 'state["auth_status"] = "failed"' in gate_source


def test_workflow_runtime_reapplies_trusted_identity_after_request_metadata() -> None:
    build_config = _class_method_source(
        WORKFLOW_RUNTIME,
        "WorkflowRuntime",
        "_build_config",
    )

    metadata_update = "request_config.update(request.metadata or {})"
    trusted_update = 'request_config.update(\n            {\n                "request_id": request_id,'

    assert metadata_update in build_config
    assert trusted_update in build_config
    assert build_config.index(metadata_update) < build_config.index(trusted_update)
    assert '"tenant_id": ctx.tenant_id' in build_config
    assert '"auth_context": auth_context' in build_config


def test_langgraph_orchestrator_does_not_construct_runtime_decision_or_provider_authority() -> None:
    source = LANGGRAPH_ORCHESTRATOR.read_text(encoding="utf-8")

    forbidden = {
        "DecisionEngine()",
        "LLMRouter()",
        "self._decision_engine",
        "self._llm_router",
        "llm_router=self._llm_router",
        "decision_engine=self._decision_engine",
    }

    found = sorted(token for token in forbidden if token in source)
    assert not found, (
        "LangGraph must consume Runtime/CORTEX decisions and Runtime provider execution "
        f"instead of constructing private authorities: {found}"
    )


def test_langgraph_runtime_nodes_consume_runtime_decisions_without_legacy_dependencies() -> None:
    source = LANGGRAPH_ORCHESTRATOR.read_text(encoding="utf-8")

    assert "return intent_detect_node(state)" in source
    assert "return response_synth_node(state)" in source
    assert "profile_manager=self._profile_manager" in source
