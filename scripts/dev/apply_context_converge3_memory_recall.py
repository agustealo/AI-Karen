from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py"
DOC = ROOT / "docs/CONTEXT_RUNTIME_ARCHITECTURE.md"

source = ORCH.read_text(encoding="utf-8")

old_import = '''from ai_karen_engine.core.memory.memory_service import (\n    MemoryType,\n    UISource,\n    WebUIMemoryService,\n)\n'''
if old_import not in source:
    raise SystemExit("expected WebUIMemoryService import block not found")
source = source.replace(old_import, "", 1)

old_sig = '''        safety_service: Optional[DistilBertService] = None,\n        memory_service: Optional[Any] = None,\n        decision_engine: Optional[DecisionEngine] = None,\n'''
new_sig = '''        safety_service: Optional[DistilBertService] = None,\n        memory_service: Optional[Any] = None,\n        memory_recall: Optional[Any] = None,\n        decision_engine: Optional[DecisionEngine] = None,\n'''
if old_sig not in source:
    raise SystemExit("constructor signature seam not found")
source = source.replace(old_sig, new_sig, 1)

old_handle = '''        self._safety_service: Optional[DistilBertService] = safety_service\n        self._memory_service: Optional[Any] = memory_service\n        self._session_state_manager: Optional[SessionStateManager] = (\n            session_state_manager\n        )\n'''
new_handle = '''        self._safety_service: Optional[DistilBertService] = safety_service\n        self._legacy_memory_service: Optional[Any] = memory_service\n        self._memory_recall: Optional[Any] = memory_recall or getattr(\n            memory_service, "recall_context", None\n        )\n        self._session_state_manager: Optional[SessionStateManager] = (\n            session_state_manager\n        )\n'''
if old_handle not in source:
    raise SystemExit("memory dependency handle seam not found")
source = source.replace(old_handle, new_handle, 1)

source = source.replace('        self._memory_resolution_failed = False\n', '', 1)

start = source.find('    async def _resolve_memory_service(self) -> Optional[Any]:\n')
end = source.find('    async def _ensure_tool_service(self) -> Optional[ToolService]:\n', start)
if start < 0 or end < 0:
    raise SystemExit("memory/session resolver block not found")
replacement = '''    async def _resolve_memory_recall(self) -> Any:\n        """Resolve the canonical Core memory recall callable.\n\n        ``memory_service`` remains a constructor compatibility input only. New\n        orchestration code consumes the Core recall contract directly.\n        """\n\n        if callable(self._memory_recall):\n            return self._memory_recall\n\n        from ai_karen_engine.core.memory.memory_runtime_manager import recall_context\n\n        self._memory_recall = recall_context\n        return self._memory_recall\n\n    async def _ensure_session_state_manager(self) -> Optional[SessionStateManager]:\n        """Return only a composition-edge injected session-state implementation."""\n\n        return self._session_state_manager\n\n'''
source = source[:start] + replacement + source[end:]

old_node = '''        async def _memory_fetch_node(state: LangGraphOrchestrationState) -> Any:\n            memory_service = await self._resolve_memory_service()\n            return await memory_fetch_node(\n                state,\n                memory_service=memory_service,\n                session_state_manager=self._session_state_manager,\n            )\n'''
new_node = '''        async def _memory_fetch_node(state: LangGraphOrchestrationState) -> Any:\n            memory_recall = await self._resolve_memory_recall()\n            return await memory_fetch_node(\n                state,\n                memory_recall=memory_recall,\n                memory_recall_top_k=self.config.memory_recall_top_k,\n                session_state_manager=self._session_state_manager,\n            )\n'''
if old_node not in source:
    raise SystemExit("memory fetch graph wrapper not found")
source = source.replace(old_node, new_node, 1)

for forbidden in ("WebUIMemoryService", "_resolve_memory_service", "_memory_resolution_failed"):
    if forbidden in source:
        raise SystemExit(f"forbidden LangGraph memory compatibility symbol remains: {forbidden}")

ORCH.write_text(source, encoding="utf-8")

doc = DOC.read_text(encoding="utf-8")
old_doc = '''LangGraphOrchestrator\n    -> injected/lazy canonical WebUIMemoryService\n    -> MemoryFetchNode\n    -> tenant-scoped memory context\n    -> graph state\n    -> PromptRuntime\n'''
new_doc = '''LangGraphOrchestrator\n    -> canonical Core memory recall contract\n    -> MemoryFetchNode\n    -> tenant-scoped memory context\n    -> graph state\n    -> PromptRuntime\n'''
if old_doc in doc:
    doc = doc.replace(old_doc, new_doc, 1)

old_debt = '''### 1. Classify memory-domain retrieval shaping\n\n`MemoryContextBuilder` still applies a memory-domain retrieval/context cap before PromptRuntime. This must be explicitly classified as retrieval shaping versus duplicate final-prompt budgeting before changing it. PromptRuntime remains the final cross-section token authority.\n'''
new_debt = '''### 1. Retire the remaining Web UI memory compatibility facade\n\nLangGraph no longer consumes `WebUIMemoryService` or its private `MemoryContextBuilder`. The remaining facade is still used by training, scheduling, learning, bootstrap, and older service dependencies. Migrate those consumers by domain before deleting the facade. PromptRuntime remains the final cross-section token authority; memory retrieval uses a validated, config-driven result-count bound rather than a second prompt-token budget.\n'''
if old_debt in doc:
    doc = doc.replace(old_debt, new_debt, 1)
DOC.write_text(doc, encoding="utf-8")
