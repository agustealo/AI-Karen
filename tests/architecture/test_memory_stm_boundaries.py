from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_MEMORY = ROOT / "src" / "ai_karen_engine" / "core" / "memory"


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
    assert "PostgresEventSource" in runtime
    assert "PostgresEntityResolver" in runtime
    assert "ProjectionManager" in runtime
    assert "HotStateWorker" in runtime


def test_no_default_tenant_in_canonical_memory_factory() -> None:
    source = _text("types/base.py")
    assert 'tenant_id: str = "default"' not in source
    assert "explicit non-default tenant_id" in source


def test_legacy_chat_memory_config_is_quarantined_from_canonical_runtime() -> None:
    """Historical Redis/Milvus-era config must never regain canonical authority."""

    canonical_files = (
        "memory_runtime_manager.py",
        "formation.py",
        "retrieval/retrieval_router.py",
        "stm/contracts.py",
    )
    for relative in canonical_files:
        source = _text(relative)
        assert "chat_memory_config" not in source, (
            f"canonical memory surface imported legacy config: {relative}"
        )


def test_legacy_redis_helpers_are_absent_from_canonical_memory_cognition() -> None:
    """Compatibility Redis helpers may remain in Platform but not active Core."""

    canonical_files = (
        "memory_runtime_manager.py",
        "formation.py",
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
