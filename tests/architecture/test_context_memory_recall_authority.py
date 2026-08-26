from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_langgraph_consumes_core_memory_recall_not_web_ui_facade() -> None:
    orchestrator = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
    )
    node = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py"
    )

    assert "WebUIMemoryService" not in orchestrator
    assert "_resolve_memory_service" not in orchestrator
    assert "memory_recall=memory_recall" in orchestrator
    assert "memory_runtime_manager import recall_context" in orchestrator

    assert "build_context" not in node
    assert "memory_service" not in node
    assert "self._memory_recall" in node
    assert "await self._memory_recall(" in node
    assert "tenant_id=str(tenant_id)" in node
    assert 'context["memories"] = results' in node


def test_memory_fetch_does_not_own_prompt_token_budget() -> None:
    node = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py"
    )
    config = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/contracts/orchestration_config.py"
    )
    orchestrator = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
    )

    assert "max_context_tokens" not in node
    assert "total_tokens" not in node
    assert "// 4" not in node
    assert "top_k=self._memory_recall_top_k" in node
    assert "memory_recall_top_k: int = 10" in config
    assert "memory_recall_top_k must be between 1 and 50" in config
    assert "memory_recall_top_k=self.config.memory_recall_top_k" in orchestrator


def test_session_continuity_remains_composition_edge_injected() -> None:
    orchestrator = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
    )
    compat = _text("src/ai_karen_engine/core/runtime/session_state_manager_compat.py")
    adapter = _text(
        "src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager_adapter.py"
    )

    assert "SessionStateManager = SessionStatePort" in compat
    assert "SessionStateManager(" not in orchestrator
    assert "Return only a composition-edge injected session-state implementation" in orchestrator
    assert "Core deliberately does not discover" in adapter
    assert "SessionStatePort when constructing the orchestrator" in adapter


def test_web_ui_memory_facade_is_retained_only_as_migration_debt() -> None:
    memory_service = _text("src/ai_karen_engine/core/memory/memory_service.py")
    package_root = _text("src/ai_karen_engine/core/memory/__init__.py")

    assert "class WebUIMemoryService" in memory_service
    assert '"WebUIMemoryService"' not in package_root
    assert '"MemoryRuntimeManager"' in package_root
    assert '"recall_context"' in package_root
