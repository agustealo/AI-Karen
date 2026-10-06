from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
APPROVAL_ROUTE = (
    ROOT / "src/ai_karen_engine/api_routes/automation/approvals.py"
)
CHAT_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
LANGGRAPH = (
    ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
)
MIGRATION = (
    ROOT
    / "supabase/migrations/20261006030000_26_runtime_human_approval_authority.sql"
)


def test_approval_router_is_mounted_by_canonical_router_registry() -> None:
    source = ROUTERS.read_text(encoding="utf-8")

    assert "automation.approvals import router as approvals_router" in source
    assert "RouterSpec(approvals_router" in source


def test_approval_route_contains_no_placeholder_execution() -> None:
    source = APPROVAL_ROUTE.read_text(encoding="utf-8")

    assert "return [] # Placeholder" not in source
    assert 'approved"}' not in source
    assert "get_approval_service()" in source
    assert "This endpoint never executes the action" in source


def test_runtime_enforces_human_gate_before_execution_paths() -> None:
    source = CHAT_RUNTIME.read_text(encoding="utf-8")

    gate_index = source.index(
        "approval_gate = await self._resolve_human_approval_gate(request, decision)"
    )
    simple_index = source.index("text, provider_meta = await self._run_simple(")
    graph_index = source.index("text, provider_meta = await self._run_graph(")

    assert gate_index < simple_index
    assert gate_index < graph_index
    assert 'type=ChatStreamEventType.APPROVAL' in source


def test_langgraph_has_no_independent_approval_authority() -> None:
    source = LANGGRAPH.read_text(encoding="utf-8")
    safety = (
        ROOT
        / "src/ai_karen_engine/core/langgraph_orchestrator/nodes/safety_gate.py"
    ).read_text(encoding="utf-8")
    node_exports = (
        ROOT
        / "src/ai_karen_engine/core/langgraph_orchestrator/nodes/__init__.py"
    ).read_text(encoding="utf-8")
    config = (
        ROOT
        / "src/ai_karen_engine/core/langgraph_orchestrator/contracts/orchestration_config.py"
    ).read_text(encoding="utf-8")

    assert 'workflow.add_node("approval_gate"' not in source
    assert "_should_require_approval" not in source
    assert "_check_approval_status" not in source
    assert '"review": END' in source
    assert "runtime_authority_mismatch:safety_review_required" in source
    assert '"sensitive" in str(result)' not in source

    assert 'state["requires_approval"] = True' not in safety
    assert "approval_gate_node" not in node_exports
    assert "ApprovalGateNode" not in node_exports
    assert "enable_approval_gate" not in config
    assert not (
        ROOT
        / "src/ai_karen_engine/core/langgraph_orchestrator/nodes/approval_gate.py"
    ).exists()


def test_approval_schema_is_tenant_scoped_one_shot_and_rls_enforced() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "tenant_id uuid NOT NULL" in source
    assert "user_id uuid NOT NULL" in source
    assert "request_fingerprint text NOT NULL" in source
    assert "'consumed'" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "runtime_approval_tenant_scope" in source


def test_resume_ingress_rebuilds_server_side_and_reenters_chat_runtime() -> None:
    source = (ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py").read_text(
        encoding="utf-8"
    )
    ui_source = (
        ROOT
        / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx"
    ).read_text(encoding="utf-8")

    assert '@router.post("/chat/approvals/{approval_id}/resume")' in source
    assert "build_resume_request(" in source
    assert "_sse(runtime_request)" in source
    assert "original_input" not in ui_source
    assert "/api/chat/approvals/${approvalResume?.approvalId}/resume" in ui_source


def test_actionable_approval_recovery_is_conversation_scoped_and_resumable() -> None:
    route = APPROVAL_ROUTE.read_text(encoding="utf-8")
    service = (
        ROOT / "src/ai_karen_engine/services/approvals.py"
    ).read_text(encoding="utf-8")
    repository = (
        ROOT
        / "src/ai_karen_engine/persistence/repositories/approval_repository.py"
    ).read_text(encoding="utf-8")
    ui = (
        ROOT
        / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx"
    ).read_text(encoding="utf-8")

    assert "conversation_id: Optional[UUID] = None" in route
    assert "list_actionable(" in route
    assert "conversation_id=str(conversation_id) if conversation_id else None" in route

    assert "async def list_actionable(" in service
    assert "conversation_id=conversation_id" in service

    assert "async def list_actionable(" in repository
    assert "status IN ('pending', 'approved')" in repository
    assert ":conversation_id IS NULL" in repository

    assert "/api/approvals?conversation_id=" in ui
    assert "approval.resume" in ui
    assert "approval_projection" in ui
    assert "reconcileActionableApprovalMessages" in ui


def test_terminal_approval_states_minimize_stored_request_payload() -> None:
    source = (
        ROOT
        / "src/ai_karen_engine/persistence/repositories/approval_repository.py"
    ).read_text(encoding="utf-8")

    assert "request_payload = '{}'::jsonb" in source
    assert "WHEN :decision = 'rejected' THEN '{}'::jsonb" in source
    assert "SET status = 'consumed'" in source
