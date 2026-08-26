from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "monitoring"
    / "probes.py"
)
APP = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
LEGACY_SERVER_APP = REPO_ROOT / "server" / "app.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"
LEGACY_HEALTH = REPO_ROOT / "server" / "health_endpoints.py"


def test_canonical_probes_define_connectivity_liveness_and_readiness() -> None:
    source = PROBES.read_text(encoding="utf-8")

    assert '@router.get("/ping")' in source
    assert '@router.get("/api/ping")' in source
    assert '@router.get("/health/live")' in source
    assert '@router.get("/ready")' in source
    assert "status_code=503" in source
    assert "database_available" in source


def test_readiness_does_not_gate_on_optional_ai_providers() -> None:
    source = PROBES.read_text(encoding="utf-8")

    forbidden = (
        "provider_registry",
        "ollama",
        "vllm",
        "transformers",
        "openai",
        "anthropic",
        "extension_health_monitor",
    )
    for token in forbidden:
        assert token not in source.lower()


def test_canonical_application_wires_probes_idempotently() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "probe_router" in source
    assert "_canonical_probe_routes_registered" in source
    assert "app.include_router(probe_router)" in source
    assert "_prune_legacy_inline_health_routes" not in source
    assert "_legacy_inline_health_routes_pruned" not in source


def test_container_healthcheck_uses_liveness_not_dependency_health() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "http://localhost:8000/health/live" in source
    assert "http://localhost:8000/ready" not in source


def test_retired_server_health_module_does_not_reappear() -> None:
    assert not LEGACY_HEALTH.exists()


def test_server_app_owns_no_health_routes() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    forbidden_route_tokens = (
        '@app.get("/health"',
        '@app.get("/api/health',
        '@app.post("/api/health',
        '@app.put("/api/health',
        '@app.delete("/api/health',
    )
    for token in forbidden_route_tokens:
        assert token not in source

    forbidden_legacy_tokens = (
        "register_health_endpoints",
        "health_endpoints",
        "degraded_mode_status_compat",
        "get_database_health_monitor",
    )
    for token in forbidden_legacy_tokens:
        assert token not in source


def test_server_app_database_shutdown_uses_app_state_not_undefined_global() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    assert 'getattr(app.state, "database_config", None)' in source
    assert "await db_config.cleanup()" in source
