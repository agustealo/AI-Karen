from pathlib import Path
import re

ROOT = Path('.')


def replace_exact(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'missing guarded block in {path}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# Conversation service must import UI DTO taxonomy from the interface layer, never Core facade.
replace_exact(
    'src/ai_karen_engine/services/memory/conversation_service.py',
    '''from ai_karen_engine.core.memory.memory_service import (\n    MemoryType,\n    UISource,\n)''',
    '''from ai_karen_engine.interfaces.ui.memory_models import (\n    MemoryType,\n    UISource,\n)''',
)

# Memory API update path already has canonical UnifiedMemoryService.update().
route = ROOT / 'src/ai_karen_engine/api_routes/memory/memory.py'
text = route.read_text(encoding='utf-8')
old = '''                success = True\n                if request.importance is not None:\n                    success = await runtime.service.update_memory_importance(\n                        tenant_id, memory_id, request.importance\n                    )\n                if success and (request.text or request.tags):\n                    await runtime.service.base_manager.delete_memory(\n                        tenant_id, memory_id\n                    )\n                    if request.text:\n                        commit_response = await runtime.service.commit(\n                            tenant_id,\n                            MemoryCommitRequest(\n                                user_id=user_id or tenant_filters["user_id"],\n                                org_id=org_id,\n                                text=request.text,\n                                tags=request.tags or [],\n                                importance=request.importance or 5,\n                                decay=request.decay or "short",\n                                metadata=tenant_filters,\n                            ),\n                        )\n                        success = commit_response.success\n                    else:\n                        new_id = await runtime.service.store_web_ui_memory(\n                            tenant_id=tenant_id,\n                            content="",\n                            user_id=user_id or tenant_filters["user_id"],\n                            ui_source=UISource.AG_UI,\n                            memory_type=MemoryType.GENERAL,\n                            tags=request.tags,\n                            importance_score=request.importance,\n                            metadata={"decay": request.decay}\n                            if request.decay\n                            else None,\n                            tenant_filters=tenant_filters,\n                        )\n                        success = new_id is not None\n'''
new = '''                updates: Dict[str, Any] = {\n                    "updated_by": user_id or tenant_filters["user_id"],\n                    "metadata": dict(tenant_filters),\n                }\n                if request.text is not None:\n                    updates["content"] = request.text\n                if request.tags is not None:\n                    updates["tags"] = request.tags\n                if request.importance is not None:\n                    updates["importance"] = request.importance\n                if request.decay is not None:\n                    updates["metadata"]["decay_tier"] = request.decay\n\n                success = await runtime.service.update(\n                    tenant_id=tenant_id,\n                    memory_id=memory_id,\n                    updates=updates,\n                    correlation_id=correlation_id,\n                )\n'''
if old not in text:
    raise SystemExit('missing guarded memory update block')
route.write_text(text.replace(old, new, 1), encoding='utf-8')

# Current architecture documentation should state the completed topology.
doc = ROOT / 'docs/CONTEXT_RUNTIME_ARCHITECTURE.md'
if doc.exists():
    d = doc.read_text(encoding='utf-8')
    old_line = 'LangGraph no longer consumes `WebUIMemoryService` or its private `MemoryContextBuilder`. The remaining facade is still used by training, scheduling, learning, bootstrap, and older service dependencies. Migrate those consumers by domain before deleting the facade. PromptRuntime remains the final cross-section token authority; memory retrieval uses a validated, config-driven result-count bound rather than a second prompt-token budget.'
    new_line = 'The legacy `WebUIMemoryService` facade and its private `MemoryContextBuilder` have been removed. Domain consumers now use canonical Unified memory contracts or the runtime memory manager through composition boundaries. PromptRuntime remains the final cross-section token authority; memory retrieval uses a validated, config-driven result-count bound rather than a second prompt-token budget.'
    if old_line in d:
        doc.write_text(d.replace(old_line, new_line, 1), encoding='utf-8')

# Tests must prove absence rather than preserving the fossil.
for path in [
    'tests/architecture/test_context_memory_boundary_convergence.py',
    'tests/architecture/test_context_memory_recall_authority.py',
    'tests/architecture/test_memory_consumer_domain_migration.py',
]:
    p = ROOT / path
    t = p.read_text(encoding='utf-8')
    t = t.replace(
        'memory_service = (ROOT / "src/ai_karen_engine/core/memory/memory_service.py").read_text(encoding="utf-8")\n',
        'memory_service_path = ROOT / "src/ai_karen_engine/core/memory/memory_service.py"\n',
    )
    t = t.replace('assert memory_service.count("class MemoryContextBuilder:") == 1', 'assert not memory_service_path.exists()')
    t = t.replace('assert "class WebUIMemoryService" in memory_service', 'assert not memory_service_path.exists()')
    p.write_text(t, encoding='utf-8')

# Context CI should prove the legacy file is absent, not count a class in it.
wf = ROOT / '.github/workflows/context-authority-contract.yml'
w = wf.read_text(encoding='utf-8')
w = w.replace(
    '          test "$(grep -c \'^class MemoryContextBuilder:\' src/ai_karen_engine/core/memory/memory_service.py)" -eq 1\n',
    '          test ! -e src/ai_karen_engine/core/memory/memory_service.py\n',
)
wf.write_text(w, encoding='utf-8')

# Memory consumer contract should explicitly prove permanent deletion.
wf2 = ROOT / '.github/workflows/memory-consumer-contract.yml'
w2 = wf2.read_text(encoding='utf-8')
needle = '          set -euo pipefail\n'
if 'test ! -e src/ai_karen_engine/core/memory/memory_service.py' not in w2:
    w2 = w2.replace(needle, needle + '          test ! -e src/ai_karen_engine/core/memory/memory_service.py\n', 1)
wf2.write_text(w2, encoding='utf-8')
