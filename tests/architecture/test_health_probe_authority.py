from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = REPO_ROOT / "src" / "ai_karen_engine" / "api_routes" / "monitoring" / "probes.py"
APP = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_canonical_probes_define_liveness_and_readiness() -> None:
    source = PROBES.read_text(encoding="utf-8")

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
