from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dead_simulated_planning_api_is_removed() -> None:
    route = ROOT / "src/ai_karen_engine/api_routes/cognition/planning.py"
    assert not route.exists()

    routers = _text("src/ai_karen_engine/server/routers.py")
    assert "cognition.planning" not in routers
    assert "/api/plans" not in routers


def test_cortex_continuity_planner_is_decision_only() -> None:
    planner = _text(
        "src/ai_karen_engine/core/cortex/continuity/planner.py"
    )

    for forbidden in (
        "sqlalchemy",
        "async_transaction_scope",
        "Postgres",
        "execute_plan",
        "invoke_tool",
        "ActionExecutionGate",
        "automation",
    ):
        assert forbidden not in planner


def test_runtime_continuity_consumes_context_evidence_not_database() -> None:
    runtime = _text(
        "src/ai_karen_engine/core/runtime/continuity_runtime.py"
    )

    assert "CognitiveContext" in runtime
    assert "EvidenceSource.MEMORY" in runtime
    assert "plan_from_context" in runtime
    assert "postgres" not in runtime.casefold()
    assert "sqlalchemy" not in runtime.casefold()


def test_chat_runtime_surfaces_continuity_as_workflow_context() -> None:
    chat = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert "self._resolve_continuity_context(request, decision)" in chat
    assert '{"continuity": request.metadata["continuity_context"]}' in chat
    assert '"continuity_context"' in chat
    assert chat.count("self._resolve_continuity_context(request, decision)") >= 2


def test_continuity_is_not_stored_as_memory_or_authorized_execution() -> None:
    contracts = _text(
        "src/ai_karen_engine/core/cortex/continuity/contracts.py"
    )
    runtime = _text(
        "src/ai_karen_engine/core/runtime/continuity_runtime.py"
    )

    assert '"execution_authorized": False' in contracts
    assert "mutates user state" in runtime
    assert "memory_items" not in runtime


def test_runtime_composition_owns_continuity_coordinator() -> None:
    composition = _text(
        "src/ai_karen_engine/core/runtime/composition.py"
    )

    assert "continuity_runtime: ContinuityRuntime | None" in composition
    assert "continuity_runtime=ContinuityRuntime()" in composition
