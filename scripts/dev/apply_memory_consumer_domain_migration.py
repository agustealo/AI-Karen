from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"expected seam not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# Runtime/lazy composition owns construction through one canonical factory.
replace_once(
    "src/ai_karen_engine/core/runtime/lazy_loading.py",
    """def create_memory_service_factory():\n    def factory():\n        from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n\n        return WebUIMemoryService()\n\n    return factory\n""",
    """def create_memory_service_factory():\n    def factory():\n        from ai_karen_engine.core.memory.service_factory import (\n            create_unified_memory_service,\n        )\n\n        return create_unified_memory_service()\n\n    return factory\n""",
)

replace_once(
    "src/ai_karen_engine/core/services/dependencies.py",
    """        from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n        from ai_karen_engine.database.client import MultiTenantPostgresClient\n""",
    """        from ai_karen_engine.core.memory.service_factory import (\n            create_unified_memory_service,\n        )\n        from ai_karen_engine.database.client import MultiTenantPostgresClient\n""",
)
replace_once(
    "src/ai_karen_engine/core/services/dependencies.py",
    """                memory_service = WebUIMemoryService()\n""",
    """                memory_service = create_unified_memory_service()\n""",
)

# Training route delegates memory resolution to the service dependency boundary.
path = "src/ai_karen_engine/api_routes/training/data.py"
text = read(path)
text = text.replace(
    "from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n",
    "from ai_karen_engine.core.services.dependencies import get_memory_service\n",
    1,
)
text = text.replace(
    "def _create_autonomous_learner() -> \"AutonomousLearner\":\n",
    "async def _create_autonomous_learner() -> \"AutonomousLearner\":\n",
    1,
)
text = text.replace(
    """    return AutonomousLearner(\n        spacy_analyzer=SpacyAnalyzer(spacy_service=SpacyService()),\n        memory_service=WebUIMemoryService(),\n    )\n""",
    """    memory_service = await get_memory_service()\n    return AutonomousLearner(\n        spacy_analyzer=SpacyAnalyzer(spacy_service=SpacyService()),\n        memory_service=memory_service,\n    )\n""",
    1,
)
text = text.replace("learner = _create_autonomous_learner()", "learner = await _create_autonomous_learner()", 1)
if "WebUIMemoryService" in text:
    raise SystemExit("training route still references WebUIMemoryService")
write(path, text)

# Automation route becomes async composition and reuses canonical dependency resolution.
path = "src/ai_karen_engine/api_routes/automation/scheduler.py"
text = read(path)
text = text.replace(
    "from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n",
    "",
    1,
)
text = text.replace(
    "from ai_karen_engine.core.services.dependencies import bypass_user_context_func\n",
    "from ai_karen_engine.core.services.dependencies import bypass_user_context_func, get_memory_service\n",
    1,
)
text = text.replace(
    "def get_scheduler_manager() -> SchedulerManager:\n",
    "async def get_scheduler_manager() -> SchedulerManager:\n",
    1,
)
text = text.replace("memory_service = WebUIMemoryService()", "memory_service = await get_memory_service()", 1)
text = text.replace("manager = get_scheduler_manager()", "manager = await get_scheduler_manager()")
if "WebUIMemoryService" in text:
    raise SystemExit("automation route still references WebUIMemoryService")
write(path, text)

# Learning already consumes commit/query. Change only its contract type to UnifiedMemoryService.
path = "src/ai_karen_engine/learning/autonomous_learner.py"
text = read(path)
text = text.replace(
    "from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n",
    "from ai_karen_engine.core.memory.unified_memory_service import UnifiedMemoryService\n",
    1,
)
text = text.replace("WebUIMemoryService", "UnifiedMemoryService")
write(path, text)

# Scheduling writes through UnifiedMemoryService.commit instead of UI-specific store API.
path = "src/ai_karen_engine/services/scheduling/scheduler_manager.py"
text = read(path)
text = text.replace(
    "from ai_karen_engine.core.memory.memory_service import WebUIMemoryService\n",
    "from ai_karen_engine.core.memory.unified_memory_service import (\n    MemoryCommitRequest,\n    UnifiedMemoryService,\n)\n",
    1,
)
text = text.replace("WebUIMemoryService", "UnifiedMemoryService")
old_block = '''        try:\n            from ai_karen_engine.core.memory.memory_service import MemoryType, UISource\n            \n            content = f"Training Notification: {title}\\n\\n{message}"\n            \n            await self.memory_service.store_web_ui_memory(\n                tenant_id=config.memory_tenant_id,\n                content=content,\n                user_id="system",\n                ui_source=UISource.API,\n                memory_type=MemoryType.INSIGHT,\n                tags=["autonomous_training", "notification", event_type],\n                importance_score=config.memory_importance_score,\n                ai_generated=True,\n                metadata={\n                    "event_type": event_type,\n                    "title": title,\n                    "notification_data": data or {}\n                }\n            )\n            \n            logger.info("Memory notification stored successfully")\n'''
new_block = '''        try:\n            content = f"Training Notification: {title}\\n\\n{message}"\n\n            await self.memory_service.commit(\n                tenant_id=config.memory_tenant_id,\n                request=MemoryCommitRequest(\n                    user_id="system",\n                    text=content,\n                    tags=["autonomous_training", "notification", event_type],\n                    importance=config.memory_importance_score,\n                    decay="long",\n                    metadata={\n                        "source": "scheduler",\n                        "memory_class": "semantic_long_term",\n                        "ai_generated": True,\n                        "event_type": event_type,\n                        "title": title,\n                        "notification_data": data or {},\n                    },\n                ),\n            )\n\n            logger.info("Memory notification stored successfully")\n'''
if old_block not in text:
    raise SystemExit("scheduler memory notification seam not found")
text = text.replace(old_block, new_block, 1)
write(path, text)

# Agent construction reuses the same canonical factory instead of owning DB/embedding setup.
path = "src/ai_karen_engine/agents/agent_registry.py"
text = read(path)
old = '''                from ai_karen_engine.database.client import MultiTenantPostgresClient\n                from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager\n\n                self._memory_service = UnifiedMemoryService(\n                    db_client=MultiTenantPostgresClient(),\n                    embedding_manager=EmbeddingManager()\n                )\n'''
new = '''                from ai_karen_engine.core.memory.service_factory import (\n                    create_unified_memory_service,\n                )\n\n                self._memory_service = create_unified_memory_service()\n'''
if old not in text:
    raise SystemExit("agent registry unified construction seam not found")
text = text.replace(old, new, 1)
write(path, text)

path = "src/ai_karen_engine/agents/agent_orchestrator.py"
text = read(path)
old = '''                    from ai_karen_engine.core.memory.unified_memory_service import (\n                        UnifiedMemoryService,\n                    )\n                    from ai_karen_engine.database.client import MultiTenantPostgresClient\n                    from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager\n\n                    service = UnifiedMemoryService(\n                        db_client=MultiTenantPostgresClient(),\n                        embedding_manager=EmbeddingManager(),\n                    )\n'''
new = '''                    from ai_karen_engine.core.memory.service_factory import (\n                        create_unified_memory_service,\n                    )\n\n                    service = create_unified_memory_service()\n'''
if old not in text:
    raise SystemExit("agent orchestrator unified construction seam not found")
text = text.replace(old, new, 1)
write(path, text)
