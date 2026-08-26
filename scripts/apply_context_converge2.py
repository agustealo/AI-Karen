from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ai_karen_engine"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# 1) MemoryFetchNode consumes the injected canonical memory service directly.
path = SRC / "core/langgraph_orchestrator/nodes/memory_fetch.py"
write(
    path,
    '''import logging\nimport time\nfrom typing import Any, Dict, Optional\n\nfrom ..contracts.orchestration_state import LangGraphOrchestrationState\nfrom ..context.context_manager_adapter import (\n    ensure_session_state_manager,\n    load_session_continuity,\n)\nfrom ..utils.message_serialization import message_to_history_entry\nfrom ai_karen_engine.utils.chat_helpers import wants_long_form_markdown_article\nfrom ai_karen_engine.core.memory.profile_synthesis import get_profile_service\n\nlogger = logging.getLogger(__name__)\n\n\nclass MemoryFetchNode:\n    """Fetch tenant-scoped memory/profile context without owning prompt assembly."""\n\n    def __init__(\n        self,\n        *,\n        memory_service: Optional[Any] = None,\n        session_state_manager: Optional[Any] = None,\n    ) -> None:\n        self.profile_service = get_profile_service()\n        self._memory_service = memory_service\n        self._session_state_manager = session_state_manager\n        self._session_state_resolution_failed = False\n\n    async def __call__(\n        self, state: LangGraphOrchestrationState\n    ) -> LangGraphOrchestrationState:\n        logger.info("Memory fetch processing (Profile-Synthesis-Aware)")\n\n        try:\n            errors = state.setdefault("errors", [])\n            warnings = state.setdefault("warnings", [])\n            messages = state.get("messages", [])\n            user_id = state.get("user_id")\n            tenant_id = state.get("tenant_id")\n\n            conversation_history = [\n                message_to_history_entry(message) for message in messages\n            ]\n            state["conversation_history"] = conversation_history\n\n            if not tenant_id:\n                warnings.append("Memory disabled for this turn: missing tenant_id")\n\n            if user_id:\n                try:\n                    profile_summary = await self.profile_service.get_profile_summary(\n                        user_id,\n                        tenant_id,\n                    )\n                    state["user_profile_summary"] = profile_summary.dict()\n                    legacy_profile = state.get("user_profile") or {}\n                    legacy_profile.update(\n                        {\n                            "id": str(profile_summary.user_id),\n                            "preferences": profile_summary.top_preferences,\n                            "style": profile_summary.communication_style.dict(),\n                            "roles": profile_summary.roles,\n                        }\n                    )\n                    state["user_profile"] = legacy_profile\n                    logger.debug(\n                        "Synthesized profile for %s with %s facts.",\n                        user_id,\n                        profile_summary.stable_facts_count,\n                    )\n                except Exception as prof_err:\n                    logger.warning("Profile synthesis failed for %s: %s", user_id, prof_err)\n\n            if not messages:\n                state["memory_context"] = {\n                    "conversation_history": [],\n                    "context_summary": "No prior context",\n                    "memories": [],\n                }\n                return state\n\n            user_profile = state.get("user_profile") or {}\n            user_settings = user_profile.get("preferences", {})\n            prompt = conversation_history[-1]["content"]\n            context: Dict[str, Any] = {\n                "user_id": user_id,\n                "tenant_id": tenant_id,\n                "session_id": state.get("session_id"),\n                "prompt": prompt,\n                "conversation_history": conversation_history,\n                "user_settings": user_settings,\n                "memories": [],\n            }\n\n            memory_start = time.time()\n            if tenant_id and self._memory_service is not None:\n                build_context = getattr(self._memory_service, "build_context", None)\n                if callable(build_context):\n                    try:\n                        retrieved = await build_context(\n                            tenant_id=tenant_id,\n                            user_id=user_id,\n                            query=prompt,\n                            session_id=state.get("session_id"),\n                            conversation_id=state.get("session_id"),\n                        )\n                        if isinstance(retrieved, dict):\n                            context.update(retrieved)\n                    except Exception as memory_err:\n                        logger.warning("Tenant-scoped memory recall failed: %s", memory_err)\n                        warnings.append("Memory recall unavailable for this turn")\n                else:\n                    logger.warning("Injected memory service has no build_context contract")\n                    warnings.append("Memory recall unavailable for this turn")\n\n            memory_latency = (time.time() - memory_start) * 1000\n            context.setdefault("context_metadata", {})["latency_ms"] = memory_latency\n            state["memory_context"] = context\n\n            session_state_manager = await ensure_session_state_manager(self)\n            session_id = state.get("session_id")\n            if session_state_manager and session_id:\n                session_state = await load_session_continuity(self, session_id)\n                if session_state:\n                    state["memory_context"]["session_state"] = session_state\n                    warnings.append(\n                        f"Retrieved salvaged session state for {session_id}"\n                    )\n\n            if conversation_history:\n                is_long_form = wants_long_form_markdown_article(\n                    current_user_message=conversation_history[-1]["content"],\n                    recent_messages=conversation_history,\n                )\n                state["memory_context"]["is_long_form_requested"] = is_long_form\n\n            if context.get("memories"):\n                warnings.append(\n                    f"Loaded {len(context['memories'])} contextual memories"\n                )\n\n        except Exception as exc:\n            logger.error("Memory fetch error: %s", exc)\n            state.setdefault("errors", []).append(f"Memory fetch error: {exc}")\n\n        return state\n\n\nasync def memory_fetch_node(\n    state: LangGraphOrchestrationState,\n    *,\n    memory_service: Optional[Any] = None,\n    session_state_manager: Optional[Any] = None,\n) -> LangGraphOrchestrationState:\n    """Execute memory fetch with composition-root supplied dependencies."""\n\n    node = MemoryFetchNode(\n        memory_service=memory_service,\n        session_state_manager=session_state_manager,\n    )\n    return await node(state)\n''',
)

# 2) Adapter retains session/runtime projection only. No service locator/context manager.
path = SRC / "core/langgraph_orchestrator/context/context_manager_adapter.py"
text = read(path)
text = text.replace('from .context_manager import (\n    ContextManager,\n)\n', '')
text = re.sub(
    r'\nasync def resolve_memory_service\(.*?\n\nasync def ensure_session_state_manager\(',
    '\n\nasync def ensure_session_state_manager(',
    text,
    count=1,
    flags=re.DOTALL,
)
if "ensure_context_manager" in text or "resolve_memory_service" in text or "ContextManager" in text:
    raise RuntimeError("context manager adapter still contains retired memory/context authority")
write(path, text)

# 3) Composition root owns memory-service lifecycle, not ContextManager.
path = SRC / "core/langgraph_orchestrator/langgraph_orchestrator.py"
text = read(path)
text = replace_once(
    text,
    'from .context.context_manager import ContextManager\n',
    '',
    'orchestrator ContextManager import',
)
text = replace_once(
    text,
    '        context_manager: Optional[ContextManager] = None,\n',
    '',
    'orchestrator ContextManager constructor arg',
)
text = replace_once(
    text,
    '        self._context_manager: Optional[ContextManager] = context_manager\n',
    '',
    'orchestrator ContextManager field',
)
text = re.sub(
    r'\n    async def _ensure_context_manager\(.*?(?=\n    async def _resolve_memory_service\()',
    '',
    text,
    count=1,
    flags=re.DOTALL,
)
old_resolver = '''    async def _resolve_memory_service(self) -> Optional[Any]:\n        """Resolve the shared memory service via the service registry if possible."""\n\n        if self._memory_service is not None or self._memory_resolution_failed:\n            return self._memory_service\n\n        try:\n            from ai_karen_engine.core.services.service_registry import (\n                get_memory_service,\n            )  # Lazy import\n\n            self._memory_service = await get_memory_service()\n        except Exception as exc:  # pragma: no cover - optional dependency\n            if not self._memory_resolution_failed:\n                logger.warning("Memory service unavailable: %s", exc)\n            try:\n                self._memory_service = WebUIMemoryService()\n                logger.info("Fell back to direct WebUIMemoryService initialization")\n            except Exception as fallback_exc:  # pragma: no cover - optional dependency\n                logger.warning(\n                    "Direct memory service fallback unavailable: %s", fallback_exc\n                )\n                self._memory_resolution_failed = True\n                self._memory_service = None\n\n        return self._memory_service\n'''
new_resolver = '''    async def _resolve_memory_service(self) -> Optional[Any]:\n        """Return the injected memory service or lazily create the canonical implementation."""\n\n        if self._memory_service is not None or self._memory_resolution_failed:\n            return self._memory_service\n\n        try:\n            self._memory_service = WebUIMemoryService()\n            logger.info("Initialized canonical WebUIMemoryService for LangGraph runtime")\n        except Exception as exc:  # pragma: no cover - environment-dependent resources\n            if not self._memory_resolution_failed:\n                logger.warning("Memory service unavailable: %s", exc)\n            self._memory_resolution_failed = True\n            self._memory_service = None\n\n        return self._memory_service\n'''
text = replace_once(text, old_resolver, new_resolver, 'orchestrator memory resolver')
old_node = '''        def _memory_fetch_node(state: LangGraphOrchestrationState) -> Any:\n            return memory_fetch_node(state, context_manager=self._context_manager)\n'''
new_node = '''        async def _memory_fetch_node(state: LangGraphOrchestrationState) -> Any:\n            memory_service = await self._resolve_memory_service()\n            return await memory_fetch_node(\n                state,\n                memory_service=memory_service,\n                session_state_manager=self._session_state_manager,\n            )\n'''
text = replace_once(text, old_node, new_node, 'orchestrator memory node wiring')
if "ContextManager" in text or "_context_manager" in text or "context_manager=" in text:
    raise RuntimeError("orchestrator still contains ContextManager authority")
write(path, text)

# 4) Diagnostics must remain side-effect-free and never call context services.
path = SRC / "core/langgraph_orchestrator/diagnostics.py"
text = read(path)
text = replace_once(text, 'from .context.context_manager import ContextManager\n', '', 'diagnostics import')
text = replace_once(text, '        context_manager: Optional[ContextManager] = None,\n', '', 'diagnostics arg')
text = replace_once(text, '        self._context_manager = context_manager\n', '', 'diagnostics field')
pattern = re.compile(
    r'        if self\._context_manager:\n            built_context = await self\._context_manager\.build_context\(.*?        else:\n            built_context = \{\}\n',
    re.DOTALL,
)
replacement = '''        built_context = {\n            "tenant_id": tenant_id,\n            "user_id": user_id,\n            "session_id": session_identifier,\n            "prompt": message,\n            "conversation_history": sanitized_history,\n            "user_settings": user_settings,\n            "memories": memories or [],\n        }\n'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"diagnostics side-effect removal expected one block, found {count}")
if "ContextManager" in text or "_context_manager" in text:
    raise RuntimeError("diagnostics still contains ContextManager")
write(path, text)

# 5) Remove the malformed, shadowed first MemoryContextBuilder only.
path = SRC / "core/memory/memory_service.py"
text = read(path)
first_builder = re.compile(
    r'\nclass MemoryContextBuilder:\n    conversation_id:.*?(?=\n\nclass MemoryContextBuilder:\n    """Builds conversation context)',
    re.DOTALL,
)
text, count = first_builder.subn('', text, count=1)
if count != 1:
    raise RuntimeError(f"shadow MemoryContextBuilder removal expected one block, found {count}")
if text.count("class MemoryContextBuilder:") != 1:
    raise RuntimeError("memory_service must contain exactly one MemoryContextBuilder")
write(path, text)

# 6) Delete the retired compatibility implementation after all references are removed.
manager_path = SRC / "core/langgraph_orchestrator/context/context_manager.py"
if manager_path.exists():
    manager_path.unlink()

# 7) Update canonical architecture doc to reflect retirement.
doc = ROOT / "docs/CONTEXT_RUNTIME_ARCHITECTURE.md"
text = read(doc)
text = text.replace(
    '''The remaining `ContextManager` is only a thin LangGraph compatibility adapter for memory enrichment. It does not own a general context database or final prompt composition.\n\nCurrent path:\n\n```text\nMemoryFetchNode\n    -> ContextManager.build_context()\n    -> canonical memory service enrichment\n    -> graph state\n    -> PromptRuntime\n```\n\n`ContextManager` is intentionally transitional and should disappear once LangGraph consumes Runtime-produced memory context directly.\n''',
    '''`ContextManager` has been retired. `MemoryFetchNode` receives the canonical memory service from the LangGraph composition root and writes the retrieved tenant-scoped memory envelope into graph state.\n\nCurrent path:\n\n```text\nLangGraphOrchestrator\n    -> injected/lazy canonical WebUIMemoryService\n    -> MemoryFetchNode\n    -> tenant-scoped memory context\n    -> graph state\n    -> PromptRuntime\n```\n\nThe node does not own retrieval policy or final prompt assembly.\n''',
)
text = text.replace(
    '''### 1. Retire `ContextManager`\n\n`ContextManager` is now small enough that its remaining existence is a compatibility seam rather than an architectural owner. The next context cleanup should trace `ensure_context_manager()` and move memory enrichment directly behind the runtime/memory port used by LangGraph.\n\n### 2. Decide the future of `FileContextStore`\n''',
    '''### 1. Classify memory-domain retrieval shaping\n\n`MemoryContextBuilder` still applies a memory-domain retrieval/context cap before PromptRuntime. This must be explicitly classified as retrieval shaping versus duplicate final-prompt budgeting before changing it. PromptRuntime remains the final cross-section token authority.\n\n### 2. Decide the future of `FileContextStore`\n''',
)
write(doc, text)

# 8) Add permanent architecture proof.
test_path = ROOT / "tests/architecture/test_context_memory_boundary_convergence.py"
write(
    test_path,
    '''from __future__ import annotations\n\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[2]\n\n\ndef _text(relative: str) -> str:\n    return (ROOT / relative).read_text(encoding="utf-8")\n\n\ndef test_context_manager_is_retired_without_replacement() -> None:\n    assert not (ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager.py").exists()\n    adapter = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager_adapter.py")\n    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")\n    diagnostics = _text("src/ai_karen_engine/core/langgraph_orchestrator/diagnostics.py")\n    assert "ContextManager" not in adapter + orchestrator + diagnostics\n    assert "ensure_context_manager" not in adapter\n    assert "resolve_memory_service" not in adapter\n\n\ndef test_langgraph_injects_memory_service_into_memory_fetch() -> None:\n    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")\n    node = _text("src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py")\n    assert "memory_service = await self._resolve_memory_service()" in orchestrator\n    assert "memory_service=memory_service" in orchestrator\n    assert "session_state_manager=self._session_state_manager" in orchestrator\n    assert 'getattr(self._memory_service, "build_context", None)' in node\n    assert "tenant_id and self._memory_service is not None" in node\n    assert "Memory disabled for this turn: missing tenant_id" in node\n\n\ndef test_stale_memory_service_registry_lookup_is_removed() -> None:\n    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")\n    adapter = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager_adapter.py")\n    assert "core.services.service_registry" not in orchestrator\n    assert "get_memory_service" not in orchestrator\n    assert "core.services.service_registry" not in adapter\n\n\ndef test_diagnostics_does_not_call_memory_or_context_services() -> None:\n    diagnostics = _text("src/ai_karen_engine/core/langgraph_orchestrator/diagnostics.py")\n    assert "build_context(" not in diagnostics\n    assert '"conversation_history": sanitized_history' in diagnostics\n    assert '"memories": memories or []' in diagnostics\n\n\ndef test_shadow_memory_context_builder_is_removed_but_domain_cap_is_unchanged() -> None:\n    memory_service = _text("src/ai_karen_engine/core/memory/memory_service.py")\n    assert memory_service.count("class MemoryContextBuilder:") == 1\n    assert "self.max_context_tokens = 2000" in memory_service\n    assert "memory_tokens = len(memory.content) // 4" in memory_service\n\n\ndef test_context_doc_records_direct_memory_boundary() -> None:\n    doc = _text("docs/CONTEXT_RUNTIME_ARCHITECTURE.md")\n    assert "`ContextManager` has been retired" in doc\n    assert "Classify memory-domain retrieval shaping" in doc\n''',
)
