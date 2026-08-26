from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_context_manager_is_retired_without_replacement() -> None:
    assert not (ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager.py").exists()
    adapter = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager_adapter.py")
    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")
    diagnostics = _text("src/ai_karen_engine/core/langgraph_orchestrator/diagnostics.py")
    assert "ContextManager" not in adapter + orchestrator + diagnostics
    assert "ensure_context_manager" not in adapter
    assert "resolve_memory_service" not in adapter


def test_langgraph_injects_core_memory_recall_into_memory_fetch() -> None:
    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")
    node = _text("src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py")
    assert "memory_recall = await self._resolve_memory_recall()" in orchestrator
    assert "memory_recall=memory_recall" in orchestrator
    assert "memory_runtime_manager import recall_context" in orchestrator
    assert "memory_recall_top_k=self.config.memory_recall_top_k" in orchestrator
    assert "session_state_manager=self._session_state_manager" in orchestrator
    assert "await self._memory_recall(" in node
    assert "tenant_id and self._memory_recall is not None" in node
    assert "top_k=self._memory_recall_top_k" in node
    assert "Memory disabled for this turn: missing tenant_id" in node


def test_stale_memory_service_registry_lookup_is_removed() -> None:
    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")
    adapter = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager_adapter.py")
    assert "get_memory_service" not in orchestrator
    assert "service_registry import get_memory_service" not in orchestrator
    assert "get_memory_service" not in adapter


def test_diagnostics_does_not_call_memory_or_context_services() -> None:
    diagnostics = _text("src/ai_karen_engine/core/langgraph_orchestrator/diagnostics.py")
    assert "build_context(" not in diagnostics
    assert '"conversation_history": sanitized_history' in diagnostics
    assert '"memories": memories or []' in diagnostics


def test_shadow_memory_context_builder_remains_outside_langgraph_authority() -> None:
    memory_service = _text("src/ai_karen_engine/core/memory/memory_service.py")
    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")
    node = _text("src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py")
    assert memory_service.count("class MemoryContextBuilder:") == 1
    assert "self.max_context_tokens = 2000" in memory_service
    assert "WebUIMemoryService" not in orchestrator
    assert "max_context_tokens" not in node
    assert "memory_tokens = len(memory.content) // 4" not in node


def test_context_doc_records_core_memory_recall_boundary() -> None:
    doc = _text("docs/CONTEXT_RUNTIME_ARCHITECTURE.md")
    assert "`ContextManager` has been retired" in doc
    assert "canonical Core memory recall contract" in doc
    assert "Retire the remaining Web UI memory compatibility facade" in doc
