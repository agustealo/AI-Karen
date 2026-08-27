from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_MEMORY = ROOT / "src" / "ai_karen_engine" / "core" / "memory"
INTEGRATIONS_MEMORY = (
    ROOT / "src" / "ai_karen_engine" / "integrations" / "memory"
)
MEMORY_CONTROL_ROUTE = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "memory"
    / "control.py"
)
POSTGRES_CONTROL = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "platform"
    / "memory"
    / "postgres"
    / "control_repository.py"
)
PLATFORM_REDIS = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "platform"
    / "memory"
    / "redis"
    / "redis_connection_manager.py"
)


def _text(relative: str) -> str:
    return (CORE_MEMORY / relative).read_text(encoding="utf-8")


def test_retrieval_router_has_no_direct_redis_or_postgres_construction() -> None:
    source = _text("retrieval/retrieval_router.py")
    forbidden = (
        "get_redis_manager",
        "redis_connection_manager",
        "PostgresEventSource",
        "PostgresEntityResolver",
        ".get_session(",
        ".get_short_term(",
    )
    for token in forbidden:
        assert token not in source, f"retrieval router leaked backend authority: {token}"


def test_projection_core_has_no_redis_backend_worker() -> None:
    projection_dir = CORE_MEMORY / "projections"
    assert not (projection_dir / "redis_worker.py").exists()

    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in projection_dir.glob("*.py")
    )
    forbidden = (
        "redis_connection_manager",
        "get_redis_manager",
        "set_short_term(",
        "get_short_term(",
        "set_session(",
        "get_session(",
        "hot_memory:",
    )
    for token in forbidden:
        assert token not in combined, f"projection core leaked Redis authority: {token}"


def test_global_retrieval_router_singleton_is_retired() -> None:
    router = _text("retrieval/retrieval_router.py")
    package = _text("retrieval/__init__.py")
    facade = _text("__init__.py")

    assert "retrieval_router = HybridRetrievalRouter()" not in router
    assert "get_retrieval_router" not in package
    assert "get_retrieval_router" not in facade


def test_runtime_is_the_explicit_platform_composition_boundary() -> None:
    runtime = _text("memory_runtime_manager.py")
    assert "RedisSTMAdapter" in runtime
    assert runtime.count("RedisSTMAdapter()") == 1
    assert "self._stm =" in runtime
    assert "self._build_neuro_recall(self._stm)" in runtime
    assert "self._build_formation_service(" in runtime
    assert "self._build_control_service()" in runtime
    assert "PostgresMemoryControlRepository" in runtime
    assert "PostgresEventSource" in runtime
    assert "PostgresEntityResolver" in runtime
    assert "ProjectionManager" in runtime
    assert "HotStateWorker" in runtime


def test_canonical_runtime_blocks_direct_ledger_writes() -> None:
    runtime = _text("memory_runtime_manager.py")
    assert "async def _commit_to_ledger" in runtime
    assert "MemoryFormationService/NeuroVault" in runtime
    assert "raise RuntimeError(" in runtime
    assert "super()._commit_to_ledger" not in runtime


def test_memory_control_route_uses_runtime_feature_flag_authority() -> None:
    source = MEMORY_CONTROL_ROUTE.read_text(encoding="utf-8")
    assert "get_feature_flags" in source
    assert "manager.flags" not in source
    assert ".set_shadow_mode(" not in source
    assert "flags.set_tenant_override" in source
    assert "flags.set_user_override" in source
    assert "flags.set_global" in source


def test_memory_control_route_delegates_persistence_to_control_service() -> None:
    source = MEMORY_CONTROL_ROUTE.read_text(encoding="utf-8")
    assert "get_memory_control_service" in source
    assert "_memory_control().inspect_memory_state" in source
    assert "_memory_control().list_consent_scopes" in source
    assert "_memory_control().set_consent_scope" in source
    assert "_memory_control().list_retention_policies" in source
    assert "_memory_control().set_retention_policy" in source
    assert "_memory_control().export_promoted_artifacts" in source
    assert "sqlalchemy" not in source.lower()


def test_postgres_control_repository_is_the_sql_control_adapter() -> None:
    source = POSTGRES_CONTROL.read_text(encoding="utf-8")
    assert "from sqlalchemy import" in source
    assert "PostgresMemoryControlRepository" in source
    assert "MemoryControlPort" in source
    assert "MemoryFormationService" not in source
    assert "NeuroRecall" not in source


def test_no_default_tenant_in_canonical_memory_factory() -> None:
    source = _text("types/base.py")
    assert 'tenant_id: str = "default"' not in source
    assert "explicit non-default tenant_id" in source


def test_legacy_chat_memory_config_is_retired() -> None:
    assert not (CORE_MEMORY / "chat_memory_config.py").exists()


def test_core_redis_compatibility_shim_is_retired() -> None:
    assert not (CORE_MEMORY / "redis_connection_manager.py").exists()


def test_legacy_sql_memory_runtime_is_retired() -> None:
    assert not (CORE_MEMORY / "_legacy_memory_runtime_impl.py").exists()
    assert not (INTEGRATIONS_MEMORY / "legacy_memory_runtime_impl.py").exists()

    base = _text("_memory_runtime_base.py")
    assert "_legacy_memory_runtime_impl" not in base
    assert "integrations.memory.legacy_memory_runtime_impl" not in base

    for path in CORE_MEMORY.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "_legacy_memory_runtime_impl" not in source, (
            f"legacy runtime reference returned: {path.relative_to(CORE_MEMORY)}"
        )


def test_platform_redis_manager_has_no_memory_semantic_compatibility_api() -> None:
    source = PLATFORM_REDIS.read_text(encoding="utf-8")
    forbidden = (
        "def _k(",
        "def _session_k(",
        "def set_short_term(",
        "def get_short_term(",
        "def set_session(",
        "def get_session(",
        "def flush_short_term(",
        "def flush_long_term(",
        '"long_term"',
    )
    for token in forbidden:
        assert token not in source, f"Redis manager regained memory authority: {token}"


def test_legacy_redis_helpers_are_absent_from_canonical_memory_cognition() -> None:
    canonical_files = (
        "memory_runtime_manager.py",
        "formation/service.py",
        "retrieval/retrieval_router.py",
        "projections/hot_state_worker.py",
    )
    forbidden = (
        "set_short_term(",
        "get_short_term(",
        "set_session(",
        "get_session(",
    )
    for relative in canonical_files:
        source = _text(relative)
        for token in forbidden:
            assert token not in source, (
                f"canonical memory surface leaked legacy Redis helper {token}: {relative}"
            )
