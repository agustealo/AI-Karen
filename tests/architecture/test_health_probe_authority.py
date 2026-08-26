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


def test_container_healthcheck_uses_liveness_not_dependency_health() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "http://localhost:8000/health/live" in source
    assert "http://localhost:8000/ready" not in source


def test_legacy_server_health_module_registers_no_routes() -> None:
    source = LEGACY_HEALTH.read_text(encoding="utf-8")

    assert "def register_health_endpoints" in source
    assert "@app." not in source
    assert "@router." not in source

    forbidden_authority_tokens = (
        "get_database_manager",
        "get_redis_manager",
        "get_provider_registry_service",
        "get_extension_health_monitor",
        "get_extension_service_recovery_manager",
        "psutil",
    )
    for token in forbidden_authority_tokens:
        assert token not in source


def test_remaining_inline_health_debt_is_explicit_and_bounded() -> None:
    """Keep the final server.app extraction surface visible until it is deleted.

    These are migration-debt routes, not accepted health authorities. The test is
    intentionally removed when the routes move to their canonical monitoring or
    admin/operator owners.
    """

    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")
    expected_inline_routes = (
        '@app.get("/health"',
        '@app.get("/api/health/database"',
        '@app.get("/api/health/database/test"',
        '@app.get("/api/health/database/monitor"',
        '@app.get("/api/health/degraded-mode"',
    )
    for token in expected_inline_routes:
        assert token in source

    # No additional health route family may be added to the composition root.
    health_route_decorators = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("@app.") and '"/api/health' in line
    ]
    assert len(health_route_decorators) == 4
