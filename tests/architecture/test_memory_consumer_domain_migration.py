from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_web_ui_memory_service_has_no_live_consumer_imports() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "memory_service.py" and "core/memory" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if "WebUIMemoryService" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_unified_memory_construction_has_one_factory_owner() -> None:
    factory = _text("src/ai_karen_engine/core/memory/service_factory.py")
    lazy = _text("src/ai_karen_engine/core/runtime/lazy_loading.py")
    deps = _text("src/ai_karen_engine/core/services/dependencies.py")
    agent_registry = _text("src/ai_karen_engine/agents/agent_registry.py")
    agent_orchestrator = _text("src/ai_karen_engine/agents/agent_orchestrator.py")

    assert "MultiTenantPostgresClient()" in factory
    assert "EmbeddingManager()" in factory
    assert "UnifiedMemoryService(" in factory
    assert "create_unified_memory_service()" in lazy
    assert "create_unified_memory_service()" in deps
    assert "create_unified_memory_service()" in agent_registry
    assert "create_unified_memory_service()" in agent_orchestrator
    assert "UnifiedMemoryService(" not in agent_registry
    assert "UnifiedMemoryService(" not in agent_orchestrator


def test_training_and_learning_consume_unified_memory_contract() -> None:
    route = _text("src/ai_karen_engine/api_routes/training/data.py")
    learner = _text("src/ai_karen_engine/learning/autonomous_learner.py")

    assert "memory_service = await get_memory_service()" in route
    assert "await _create_autonomous_learner()" in route
    assert "tenant_id = current_user.tenant_id" in route
    assert "request.tenant_id" not in route
    assert "current_user.user_id" not in route
    assert "UnifiedMemoryService" in learner
    assert "WebUIMemoryService" not in learner
    assert ".commit(" in learner
    assert ".query(" in learner


def test_scheduling_uses_unified_commit_not_ui_store_api() -> None:
    scheduler_route = _text("src/ai_karen_engine/api_routes/automation/scheduler.py")
    scheduler = _text("src/ai_karen_engine/services/scheduling/scheduler_manager.py")

    assert "memory_service = await get_memory_service()" in scheduler_route
    assert "async def get_scheduler_manager()" in scheduler_route
    assert "MemoryCommitRequest" in scheduler
    assert "await self.memory_service.commit(" in scheduler
    assert "store_web_ui_memory" not in scheduler
    assert '"source": "scheduler"' in scheduler


def test_bootstrap_is_unified_and_tenant_explicit() -> None:
    bootstrap = _text("src/ai_karen_engine/utils/bootstrap.py")
    admin = _text("src/ai_karen_engine/api_routes/admin/admin.py")

    assert "UnifiedMemoryService" in bootstrap
    assert "WebUIMemoryService" not in bootstrap
    assert "store_web_ui_memory" not in bootstrap
    assert 'tenant_id == "default"' in bootstrap
    assert "canonical unified memory service is not storage-backed" in bootstrap
    assert 'tenant_id = getattr(request.state, "tenant_id", None)' in admin
    assert 'tenant_id="default"' not in admin


def test_runtime_gateway_resolves_but_does_not_construct_memory() -> None:
    gateway = _text("src/ai_karen_engine/core/memory/runtime_gateway.py")
    assert "UnifiedMemoryService | None" in gateway
    assert 'registry.get_service("memory_service")' in gateway
    assert "create_unified_memory_service" not in gateway
    assert "WebUIMemoryService" not in gateway
