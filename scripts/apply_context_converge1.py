from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ai_karen_engine"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# 1) PromptRuntime becomes the LangGraph context-normalization + prompt rendering owner.
prompt_service_path = SRC / "core/runtime/prompt/prompt_service.py"
text = read(prompt_service_path)
anchor = '''    def get_prompt_definition(\n        self,\n        prompt_id: str,\n        version: Optional[str] = None,\n    ) -> PromptDefinition:\n'''
methods = '''    def build_request_from_runtime_context(\n        self,\n        *,\n        messages: List[Dict[str, Any]],\n        request_context: Optional[Dict[str, Any]] = None,\n        integrated_context: Optional[Dict[str, Any]] = None,\n        profile: Optional[Dict[str, Any]] = None,\n        workflow_context: Optional[Dict[str, Any]] = None,\n        cortex_intent: Optional[Dict[str, Any]] = None,\n        token_budget: int = 4096,\n        prompt_id: Optional[str] = None,\n        prompt_version: Optional[str] = None,\n    ) -> PromptAssemblyRequest:\n        """Normalize trusted runtime context into the canonical prompt contract.\n\n        Domain owners retain ranking authority. This method does not score or\n        invent context; it preserves supplied order, deduplicates exact repeats,\n        and maps each domain into an existing PromptAssemblyRequest field.\n        """\n\n        request_context = dict(request_context or {})\n        integrated_context = dict(integrated_context or {})\n        profile_payload = dict(profile or {})\n\n        for key in ("user_facts", "project_facts"):\n            items = self._normalize_context_items(request_context.get(key), source=key)\n            if items:\n                profile_payload[key] = items\n\n        memory_items: List[Dict[str, Any]] = []\n        for key in ("episodic_items", "semantic_long_term_items", "recalled_items"):\n            memory_items.extend(\n                self._normalize_context_items(request_context.get(key), source=key)\n            )\n        memory_items.extend(\n            self._normalize_context_items(integrated_context.get("memories"), source="memory")\n        )\n        memory_items.extend(\n            self._normalize_context_items(integrated_context.get("recall"), source="recall")\n        )\n        memory_items = self._dedupe_context_items(memory_items)\n\n        instruction_lines = self._instruction_lines(integrated_context.get("instructions"))\n\n        return PromptAssemblyRequest(\n            system_instructions="\\n".join(instruction_lines),\n            profile=profile_payload,\n            memory_items=memory_items,\n            cortex_intent=dict(cortex_intent or {}),\n            workflow_context=dict(workflow_context or {}),\n            token_budget=max(1, int(token_budget or 4096)),\n            messages=[dict(message) for message in messages],\n            prompt_id=prompt_id,\n            prompt_version=prompt_version,\n        )\n\n    def render_text_prompt(self, messages: List[Dict[str, Any]]) -> str:\n        """Render canonical assembled messages for plain-text provider transports."""\n\n        return self.assembler.render_text_prompt(messages)\n\n    @staticmethod\n    def _normalize_context_items(value: Any, *, source: str) -> List[Dict[str, Any]]:\n        if not isinstance(value, list):\n            return []\n        normalized: List[Dict[str, Any]] = []\n        for index, item in enumerate(value):\n            if isinstance(item, dict):\n                content = str(item.get("content") or item.get("text") or "").strip()\n                if not content:\n                    continue\n                normalized_item = dict(item)\n                normalized_item.setdefault("id", f"{source}-{index}")\n                normalized_item.setdefault("source", source)\n                normalized_item["content"] = content\n                normalized.append(normalized_item)\n            elif item is not None:\n                content = str(item).strip()\n                if content:\n                    normalized.append(\n                        {"id": f"{source}-{index}", "source": source, "content": content}\n                    )\n        return normalized\n\n    @staticmethod\n    def _dedupe_context_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:\n        seen: set[tuple[str, str]] = set()\n        deduped: List[Dict[str, Any]] = []\n        for item in items:\n            key = (str(item.get("id") or ""), str(item.get("content") or "").strip())\n            if key in seen:\n                continue\n            seen.add(key)\n            deduped.append(item)\n        return deduped\n\n    @staticmethod\n    def _instruction_lines(value: Any) -> List[str]:\n        if not isinstance(value, list):\n            return []\n        lines: List[str] = []\n        for item in value:\n            if isinstance(item, dict):\n                content = str(item.get("content") or item.get("text") or "").strip()\n            else:\n                content = str(item or "").strip()\n            if content and content not in lines:\n                lines.append(content)\n        return lines\n\n'''
text = replace_once(text, anchor, methods + anchor, "prompt service methods")
write(prompt_service_path, text)


# 2) PromptAssembler owns transport-neutral serialization of its own messages.
prompt_assembler_path = SRC / "core/runtime/prompt/prompt_assembler.py"
text = read(prompt_assembler_path)
anchor = '''    @staticmethod\n    def _calculate_prompt_hash(\n'''
render_method = '''    @staticmethod\n    def render_text_prompt(messages: List[Dict[str, Any]]) -> str:\n        """Render assembled messages for providers that only accept text prompts."""\n\n        rendered: List[str] = []\n        for message in messages:\n            role = str(message.get("role") or "user").strip().lower()\n            content = str(message.get("content") or "").strip()\n            if not content:\n                continue\n            rendered.append(f"<{role}>\\n{content}\\n</{role}>")\n        rendered.append("<assistant>\\n")\n        return "\\n\\n".join(rendered)\n\n'''
text = replace_once(text, anchor, render_method + anchor, "prompt assembler render")
write(prompt_assembler_path, text)


# 3) Remove dead PromptRegistry budget authority.
prompt_registry_path = SRC / "core/runtime/prompt/prompt_registry.py"
text = read(prompt_registry_path)
pattern = re.compile(r"\n    def enforce_token_budget\(.*?(?=\n    def |\Z)", re.DOTALL)
text, count = pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError(f"prompt registry budget removal: found {count}")
write(prompt_registry_path, text)


# 4) Remove shadow structured-section construction from chat helpers.
chat_helpers_path = SRC / "utils/chat_helpers.py"
text = read(chat_helpers_path)
pattern = re.compile(
    r"\n\ndef _extract_fact_lines\(.*?(?=\n\ndef wants_long_form_markdown_article\()",
    re.DOTALL,
)
text, count = pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError(f"chat helper context removal: found {count}")
write(chat_helpers_path, text)


# 5) LangGraph memory fetch retrieves memory/profile only. PromptRuntime assembles later.
memory_fetch_path = SRC / "core/langgraph_orchestrator/nodes/memory_fetch.py"
text = read(memory_fetch_path)
text = replace_once(
    text,
    '''from ai_karen_engine.utils.chat_helpers import (\n    build_structured_context_sections,\n    wants_long_form_markdown_article,\n)''',
    '''from ai_karen_engine.utils.chat_helpers import wants_long_form_markdown_article''',
    "memory fetch imports",
)
block = '''            if isinstance(context, dict):\n                structured_sections = build_structured_context_sections(\n                    request_context=state.get("request_config", {}),\n                    integrated_context=context,\n                )\n                state["memory_context"]["structured_sections"] = structured_sections\n\n                if conversation_history:\n                    is_long_form = wants_long_form_markdown_article(\n                        current_user_message=conversation_history[-1]["content"],\n                        recent_messages=conversation_history,\n                    )\n                    state["memory_context"]["is_long_form_requested"] = is_long_form\n'''
replacement = '''            if isinstance(context, dict) and conversation_history:\n                is_long_form = wants_long_form_markdown_article(\n                    current_user_message=conversation_history[-1]["content"],\n                    recent_messages=conversation_history,\n                )\n                state["memory_context"]["is_long_form_requested"] = is_long_form\n'''
text = replace_once(text, block, replacement, "memory fetch structured sections")
write(memory_fetch_path, text)


# 6) Remove stale helper import from monolithic LangGraph orchestrator. It must be import-only here.
langgraph_path = SRC / "core/langgraph_orchestrator/langgraph_orchestrator.py"
text = read(langgraph_path)
if text.count("build_structured_context_sections") != 1:
    raise RuntimeError("LangGraph orchestrator unexpectedly uses build_structured_context_sections beyond import")
text = text.replace("    build_structured_context_sections,\n", "", 1)
write(langgraph_path, text)


# 7) LangGraph response synthesis uses PromptRuntime output as provider input.
response_synth_path = SRC / "core/langgraph_orchestrator/nodes/response_synth.py"
text = read(response_synth_path)
text = replace_once(
    text,
    '''from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult\nfrom ..contracts.orchestration_state import LangGraphOrchestrationState\n''',
    '''from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult\nfrom ai_karen_engine.core.runtime.prompt import get_prompt_runtime_service\nfrom ..contracts.orchestration_state import LangGraphOrchestrationState\nfrom ..utils.message_serialization import message_to_history_entry\n''',
    "response synth imports",
)
old = '''                request = ChatRequest(\n                    message=last_user_message or "",\n                    intent=intent,\n                    subtype=subtype,\n                    context={\n                        "messages": messages,\n                        "tool_results": tool_results,\n                        "reasoning_result": reasoning_result,\n                        "plan": state.get("execution_plan"),\n                        "memory": state.get("memory_context"),\n                        "user_preferences": request_preferences\n                    },\n                    preferred_model=route_decision.selected_model,\n                    stream=False, \n                    conversation_id=state.get("session_id"),\n                )\n'''
new = '''                prompt_runtime = get_prompt_runtime_service()\n                prompt_request = prompt_runtime.build_request_from_runtime_context(\n                    messages=[message_to_history_entry(message) for message in messages],\n                    request_context=request_config,\n                    integrated_context=state.get("memory_context") or {},\n                    profile=state.get("user_profile") or {},\n                    workflow_context={\n                        "plan": state.get("execution_plan"),\n                        "tool_results": tool_results,\n                        "reasoning_result": reasoning_result,\n                    },\n                    cortex_intent={\n                        "primary_intent": intent,\n                        "subtype": subtype,\n                    },\n                    token_budget=int(\n                        request_preferences.get("token_budget")\n                        or request_preferences.get("max_input_tokens")\n                        or 4096\n                    ),\n                )\n                assembled_prompt = await prompt_runtime.assemble_prompt(prompt_request)\n\n                request = ChatRequest(\n                    message=last_user_message or "",\n                    intent=intent,\n                    subtype=subtype,\n                    context={\n                        "messages": assembled_prompt.messages,\n                        "prompt_text": prompt_runtime.render_text_prompt(assembled_prompt.messages),\n                        "prompt_hash": assembled_prompt.prompt_hash,\n                        "prompt_metadata": assembled_prompt.metadata,\n                        "truncation_events": [\n                            {\n                                "section": event.section,\n                                "reason": event.reason,\n                                "items_removed": event.items_removed,\n                            }\n                            for event in assembled_prompt.truncation_events\n                        ],\n                    },\n                    preferred_model=route_decision.selected_model,\n                    stream=False,\n                    conversation_id=state.get("session_id"),\n                )\n'''
text = replace_once(text, old, new, "response synth PromptRuntime wiring")
write(response_synth_path, text)


# 8) Provider execution honors preassembled PromptRuntime text rather than rebuilding context.
for relative in (
    "core/runtime/provider_runtime.py",
    "core/model_runtime/routing/llm_router_service.py",
):
    path = SRC / relative
    text = read(path)
    needle = '''        context = request.context if isinstance(request.context, dict) else {}\n'''
    replacement = '''        context = request.context if isinstance(request.context, dict) else {}\n        prompt_text = context.get("prompt_text")\n        if isinstance(prompt_text, str) and prompt_text.strip():\n            return prompt_text.strip()\n'''
    text = replace_once(text, needle, replacement, f"{relative} canonical prompt handoff")
    write(path, text)


# 9) ContextManager shrinks to conversational memory enrichment only.
context_manager_path = SRC / "core/langgraph_orchestrator/context/context_manager.py"
write(
    context_manager_path,
    '''from __future__ import annotations\n\nimport logging\nfrom typing import Any, Dict, List, Optional\n\nlogger = logging.getLogger(__name__)\n\n\nclass ContextManager:\n    """Thin LangGraph compatibility adapter for conversational memory context.\n\n    Runtime/PromptRuntime own final context assembly. File upload state is owned\n    separately by FileContextStore. This adapter only enriches an already-scoped\n    conversational request with canonical memory-service context.\n    """\n\n    def __init__(self, memory_service: Optional[Any] = None):\n        self.memory_service = memory_service\n\n    async def build_context(\n        self,\n        *,\n        user_id: str,\n        tenant_id: Optional[str],\n        session_id: Optional[str],\n        prompt: str,\n        conversation_history: Optional[List[Dict[str, Any]]] = None,\n        user_settings: Optional[Dict[str, Any]] = None,\n        memories: Optional[List[Dict[str, Any]]] = None,\n    ) -> Dict[str, Any]:\n        context: Dict[str, Any] = {\n            "user_id": user_id,\n            "tenant_id": tenant_id,\n            "session_id": session_id,\n            "prompt": prompt,\n            "conversation_history": conversation_history or [],\n            "user_settings": user_settings or {},\n            "memories": memories or [],\n        }\n\n        memory_service = self.memory_service\n        if memory_service is not None and tenant_id and hasattr(memory_service, "build_context"):\n            try:\n                retrieved_context = await memory_service.build_context(\n                    tenant_id=tenant_id,\n                    query=prompt,\n                    user_id=user_id,\n                    session_id=session_id,\n                    conversation_id=session_id,\n                )\n                if isinstance(retrieved_context, dict):\n                    context.update(retrieved_context)\n            except TypeError:\n                logger.debug(\n                    "Memory service build_context signature mismatch; using LangGraph compatibility context"\n                )\n            except Exception as exc:\n                logger.warning("LangGraph context memory enrichment failed: %s", exc)\n        elif memory_service is not None and not tenant_id:\n            logger.warning("LangGraph memory enrichment skipped: missing tenant_id")\n\n        return context\n\n    def clear_context_cache(self) -> None:\n        """Compatibility no-op until remaining callers stop requesting cache clears."""\n\n        return None\n\n\n__all__ = ["ContextManager"]\n''',
)


# 10) File state gets its own owner instead of living in ContextManager.
file_store_path = SRC / "core/langgraph_orchestrator/context/file_context_store.py"
write(
    file_store_path,
    '''from __future__ import annotations\n\nfrom dataclasses import dataclass, field\nfrom datetime import datetime\nfrom enum import Enum\nfrom typing import Any, Dict, List, Optional\n\n\nclass ContextErrorType(str, Enum):\n    INTEGRATION_ERROR = "integration_error"\n    VALIDATION_ERROR = "validation_error"\n    NOT_FOUND = "not_found"\n    PERMISSION_DENIED = "permission_denied"\n\n\n@dataclass\nclass ContextError(Exception):\n    message: str\n    error_type: ContextErrorType\n    context_id: Optional[str] = None\n    details: Optional[Dict[str, Any]] = None\n\n    def __str__(self) -> str:\n        return self.message\n\n\nclass FileUploadStatus(str, Enum):\n    PENDING = "pending"\n    COMPLETED = "completed"\n    FAILED = "failed"\n\n\n@dataclass\nclass ContextFile:\n    file_id: str\n    filename: str\n    file_type: str\n    file_size: int\n    mime_type: str\n    content_hash: str\n    upload_status: FileUploadStatus\n    upload_timestamp: datetime\n    metadata: Dict[str, Any] = field(default_factory=dict)\n    storage_path: Optional[str] = None\n    extracted_text: Optional[str] = None\n    extracted_metadata: Dict[str, Any] = field(default_factory=dict)\n\n    def to_dict(self) -> Dict[str, Any]:\n        return {\n            "file_id": self.file_id,\n            "filename": self.filename,\n            "file_type": self.file_type,\n            "file_size": self.file_size,\n            "mime_type": self.mime_type,\n            "content_hash": self.content_hash,\n            "upload_status": self.upload_status.value,\n            "upload_timestamp": self.upload_timestamp.isoformat(),\n            "metadata": self.metadata,\n            "storage_path": self.storage_path,\n            "extracted_text": self.extracted_text,\n            "extracted_metadata": self.extracted_metadata,\n        }\n\n\n@dataclass\nclass FileContextData:\n    context_id: Optional[str] = None\n    files: List[ContextFile] = field(default_factory=list)\n    saved_contexts: List[Dict[str, Any]] = field(default_factory=list)\n    file_context: List[Dict[str, Any]] = field(default_factory=list)\n\n\n@dataclass\nclass FileContextResponse:\n    success: bool\n    context_data: Optional[FileContextData] = None\n    error_message: Optional[str] = None\n\n\n@dataclass\nclass FileContextUpdateRequest:\n    files: Optional[List[ContextFile]] = None\n    saved_contexts: Optional[List[Dict[str, Any]]] = None\n    file_context: Optional[List[Dict[str, Any]]] = None\n\n\nclass FileContextStore:\n    """Process-local compatibility store for LangGraph file-upload metadata only."""\n\n    def __init__(self) -> None:\n        self._contexts: Dict[str, FileContextData] = {}\n\n    async def get_context(self, context_id: str) -> FileContextResponse:\n        if not context_id:\n            return FileContextResponse(success=False, error_message="context_id is required")\n        data = self._contexts.setdefault(context_id, FileContextData(context_id=context_id))\n        return FileContextResponse(success=True, context_data=data)\n\n    async def update_context(\n        self,\n        context_id: str,\n        request: Optional[FileContextUpdateRequest] = None,\n    ) -> FileContextResponse:\n        if not context_id:\n            return FileContextResponse(success=False, error_message="context_id is required")\n        data = self._contexts.setdefault(context_id, FileContextData(context_id=context_id))\n        payload = request or FileContextUpdateRequest()\n        if payload.files is not None:\n            data.files = list(payload.files)\n        if payload.saved_contexts is not None:\n            data.saved_contexts = list(payload.saved_contexts)\n        if payload.file_context is not None:\n            data.file_context = list(payload.file_context)\n        return FileContextResponse(success=True, context_data=data)\n\n\n__all__ = [\n    "ContextError",\n    "ContextErrorType",\n    "ContextFile",\n    "FileContextData",\n    "FileContextResponse",\n    "FileContextStore",\n    "FileContextUpdateRequest",\n    "FileUploadStatus",\n]\n''',
)


# 11) FileUploadService depends on FileContextStore, not conversational ContextManager.
file_upload_path = SRC / "core/langgraph_orchestrator/context/file_upload_service.py"
text = read(file_upload_path)
old_import = '''from .context_manager_adapter import (\n    ContextManager,\n    ContextData,\n    ContextError,\n    ContextErrorType,\n    ContextUpdateRequest,\n)\n'''
new_import = '''from .file_context_store import (\n    ContextError,\n    ContextErrorType,\n    ContextFile,\n    FileContextStore,\n    FileContextUpdateRequest,\n    FileUploadStatus,\n)\n'''
text = replace_once(text, old_import, new_import, "file upload imports")
text = replace_once(text, "        context_manager: ContextManager,\n", "        file_context_store: FileContextStore,\n", "file upload ctor arg")
text = replace_once(text, "        self.context_manager = context_manager\n", "        self.file_context_store = file_context_store\n", "file upload ctor assignment")
text = text.replace("self.context_manager", "self.file_context_store")
text = text.replace("ContextUpdateRequest", "FileContextUpdateRequest")
# The old dynamic import is no longer valid or needed.
text = text.replace("            from .context_manager_adapter import ContextFile, FileUploadStatus\n\n", "")
write(file_upload_path, text)


# 12) Retire the orphaned deleted-package test. Its live semantics are now covered by PromptRuntime tests.
old_test = ROOT / "tests/core/context/test_context_contracts.py"
if not old_test.exists():
    raise RuntimeError("expected orphaned core/context test to exist")
old_test.unlink()

print("CONTEXT-CONVERGE-1 patch applied")
