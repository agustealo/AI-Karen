from pathlib import Path

ROOT = Path('.')


def replace_exact(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'missing guarded block in {path}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


replace_exact(
    'src/ai_karen_engine/services/memory/conversation_service.py',
    '''from ai_karen_engine.core.memory.memory_service import (\n    MemoryType,\n    UISource,\n)''',
    '''from ai_karen_engine.interfaces.ui.memory_models import (\n    MemoryType,\n    UISource,\n)''',
)

route = ROOT / 'src/ai_karen_engine/api_routes/memory/memory.py'
text = route.read_text(encoding='utf-8')
old = '''                success = True\n                if request.importance is not None:\n                    success = await runtime.service.update_memory_importance(\n                        tenant_id, memory_id, request.importance\n                    )\n                if success and (request.text or request.tags):\n                    await runtime.service.base_manager.delete_memory(\n                        tenant_id, memory_id\n                    )\n                    if request.text:\n                        commit_response = await runtime.service.commit(\n                            tenant_id,\n                            MemoryCommitRequest(\n                                user_id=user_id or tenant_filters["user_id"],\n                                org_id=org_id,\n                                text=request.text,\n                                tags=request.tags or [],\n                                importance=request.importance or 5,\n                                decay=request.decay or "short",\n                                metadata=tenant_filters,\n                            ),\n                        )\n                        success = commit_response.success\n                    else:\n                        new_id = await runtime.service.store_web_ui_memory(\n                            tenant_id=tenant_id,\n                            content="",\n                            user_id=user_id or tenant_filters["user_id"],\n                            ui_source=UISource.AG_UI,\n                            memory_type=MemoryType.GENERAL,\n                            tags=request.tags,\n                            importance_score=request.importance,\n                            metadata={"decay": request.decay}\n                            if request.decay\n                            else None,\n                            tenant_filters=tenant_filters,\n                        )\n                        success = new_id is not None\n'''
new = '''                updates: Dict[str, Any] = {\n                    "updated_by": user_id or tenant_filters["user_id"],\n                    "metadata": dict(tenant_filters),\n                }\n                if request.text is not None:\n                    updates["content"] = request.text\n                if request.tags is not None:\n                    updates["tags"] = request.tags\n                if request.importance is not None:\n                    updates["importance"] = request.importance\n                if request.decay is not None:\n                    updates["metadata"]["decay_tier"] = request.decay\n\n                success = await runtime.service.update(\n                    tenant_id=tenant_id,\n                    memory_id=memory_id,\n                    updates=updates,\n                    correlation_id=correlation_id,\n                )\n'''
if old not in text:
    raise SystemExit('missing guarded memory update block')
route.write_text(text.replace(old, new, 1), encoding='utf-8')

doc = ROOT / 'docs/CONTEXT_RUNTIME_ARCHITECTURE.md'
if doc.exists():
    d = doc.read_text(encoding='utf-8')
    old_line = 'LangGraph no longer consumes `WebUIMemoryService` or its private `MemoryContextBuilder`. The remaining facade is still used by training, scheduling, learning, bootstrap, and older service dependencies. Migrate those consumers by domain before deleting the facade. PromptRuntime remains the final cross-section token authority; memory retrieval uses a validated, config-driven result-count bound rather than a second prompt-token budget.'
    new_line = 'The legacy `WebUIMemoryService` facade and its private `MemoryContextBuilder` have been removed. Domain consumers now use canonical Unified memory contracts or the runtime memory manager through composition boundaries. PromptRuntime remains the final cross-section token authority; memory retrieval uses a validated, config-driven result-count bound rather than a second prompt-token budget.'
    if old_line in d:
        doc.write_text(d.replace(old_line, new_line, 1), encoding='utf-8')
