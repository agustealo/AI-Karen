from __future__ import annotations

from pathlib import Path

path = Path(__file__).with_name("apply_context_converge2.py")
text = path.read_text(encoding="utf-8")
needle = '''text = replace_once(text, old_node, new_node, 'orchestrator memory node wiring')
if "ContextManager" in text or "_context_manager" in text or "context_manager=" in text:
    raise RuntimeError("orchestrator still contains ContextManager authority")
'''
replacement = '''text = replace_once(text, old_node, new_node, 'orchestrator memory node wiring')
text = replace_once(
    text,
    ''' + '"""' + '''        diagnostics_engine = DiagnosticsEngine(\n            decision_engine=self._decision_engine,\n            context_manager=await self._ensure_context_manager(),\n            llm_router=self._llm_router,\n            profile_manager=self._profile_manager,\n        )\n''' + '"""' + ''',
    ''' + '"""' + '''        diagnostics_engine = DiagnosticsEngine(\n            decision_engine=self._decision_engine,\n            llm_router=self._llm_router,\n            profile_manager=self._profile_manager,\n        )\n''' + '"""' + ''',
    'orchestrator diagnostics ContextManager wiring',
)
text = replace_once(
    text,
    ''' + '"""' + '''        if self._context_manager:\n            self._context_manager.clear_context_cache()\n''' + '"""' + ''',
    "",
    'orchestrator ContextManager shutdown hook',
)
_remaining = [
    f"{index}: {line}"
    for index, line in enumerate(text.splitlines(), start=1)
    if "ContextManager" in line or "_context_manager" in line or "context_manager=" in line
]
if _remaining:
    raise RuntimeError("orchestrator still contains ContextManager authority: " + " | ".join(_remaining))
'''
if text.count(needle) != 1:
    raise RuntimeError("converge-2 driver could not locate orchestrator guard")
text = text.replace(needle, replacement, 1)
code = compile(text, str(path), "exec")
exec(code, {"__name__": "__main__", "__file__": str(path)})

root = path.resolve().parents[1]

# Migrate the original tenant contract from the retired wrapper to the direct
# MemoryFetchNode boundary. Tenant identity must be passed explicitly and must
# never fall back to user/session identity in the node.
authority_path = root / "tests/architecture/test_context_authority_convergence.py"
authority = authority_path.read_text(encoding="utf-8")
old = '''def test_langgraph_context_adapter_preserves_tenant_identity() -> None:\n    manager_source = (\n        CORE\n        / "langgraph_orchestrator"\n        / "context"\n        / "context_manager.py"\n    ).read_text(encoding="utf-8")\n    node_source = (\n        CORE / "langgraph_orchestrator" / "nodes" / "memory_fetch.py"\n    ).read_text(encoding="utf-8")\n\n    assert "tenant_id=user_id" not in manager_source\n    assert "tenant_id=tenant_id" in manager_source\n    assert "tenant_id=tenant_id" in node_source\n'''
new = '''def test_langgraph_memory_boundary_preserves_tenant_identity() -> None:\n    node_source = (\n        CORE / "langgraph_orchestrator" / "nodes" / "memory_fetch.py"\n    ).read_text(encoding="utf-8")\n\n    assert 'tenant_id = state.get("tenant_id")' in node_source\n    assert "tenant_id=tenant_id" in node_source\n    assert "tenant_id=user_id" not in node_source\n    assert "tenant_id or conversation_id" not in node_source\n    assert "Memory disabled for this turn: missing tenant_id" in node_source\n'''
if authority.count(old) != 1:
    raise RuntimeError("tenant authority contract migration did not match exactly once")
authority_path.write_text(authority.replace(old, new, 1), encoding="utf-8")

# File-upload isolation is now stronger: the conversational ContextManager no
# longer exists at all, while the file-specific store remains explicit.
consumption_path = root / "tests/architecture/test_context_langgraph_consumption.py"
consumption = consumption_path.read_text(encoding="utf-8")
old = '''def test_file_context_is_separate_from_conversation_context() -> None:\n    manager = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager.py")\n    file_store = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_context_store.py")\n    uploader = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_upload_service.py")\n    assert "class ContextFile" not in manager\n    assert "_context_store" not in manager\n    assert "async def get_context" not in manager\n    assert "async def update_context" not in manager\n    assert "class FileContextStore" in file_store\n    assert "class ContextFile" in file_store\n    assert "FileContextUpdateRequest" in uploader\n    assert "FileFileContextUpdateRequest" not in uploader\n'''
new = '''def test_file_context_is_separate_from_conversation_context() -> None:\n    manager_path = ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager.py"\n    file_store = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_context_store.py")\n    uploader = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_upload_service.py")\n    assert not manager_path.exists()\n    assert "class FileContextStore" in file_store\n    assert "class ContextFile" in file_store\n    assert "FileContextUpdateRequest" in uploader\n    assert "FileFileContextUpdateRequest" not in uploader\n'''
if consumption.count(old) != 1:
    raise RuntimeError("file/context separation contract migration did not match exactly once")
consumption_path.write_text(consumption.replace(old, new, 1), encoding="utf-8")

# The orchestrator still legitimately resolves tool services through the
# existing service registry. This context sprint only retires the stale memory
# service locator, so the contract must be memory-specific.
boundary_path = root / "tests/architecture/test_context_memory_boundary_convergence.py"
boundary = boundary_path.read_text(encoding="utf-8")
boundary = boundary.replace(
    '    assert "core.services.service_registry" not in orchestrator\n    assert "get_memory_service" not in orchestrator\n    assert "core.services.service_registry" not in adapter\n',
    '    assert "get_memory_service" not in orchestrator\n    assert "service_registry import get_memory_service" not in orchestrator\n    assert "get_memory_service" not in adapter\n',
)
if 'assert "core.services.service_registry" not in orchestrator' in boundary:
    raise RuntimeError("memory service registry contract remains overbroad")
boundary_path.write_text(boundary, encoding="utf-8")
