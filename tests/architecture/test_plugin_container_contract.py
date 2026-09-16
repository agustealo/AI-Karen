from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker" / "Dockerfile.plugins"
WORKFLOW = ROOT / ".github" / "workflows" / "plugin-ci.yml"


def test_plugin_image_reuses_canonical_runtime_and_health_authority() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "ENV PYTHONPATH=/app/src" in source
    assert "ai_karen_engine.app:create_app" in source
    assert 'CMD ["python", "-m", "uvicorn"' in source
    assert "http://localhost:8000/health/live" in source
    assert "/api/health/system" not in source
    assert '"$WORKERS"' not in source
    assert '"$WORKER_CLASS"' not in source


def test_plugin_ci_builds_a_deployable_immutable_image_and_smokes_it() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "'docker/Dockerfile.plugins'" in source
    assert "'tests/architecture/test_plugin_container_contract.py'" in source
    assert "ghcr.io/${{ github.repository_owner }}/plugin-ecosystem" in source
    assert "type=raw,value=${{ github.sha }}" in source
    assert "load: ${{ github.event_name == 'pull_request' }}" in source
    assert "Smoke loaded plugin image contract" in source
    assert "steps.build.outputs.digest" in source
    assert 'plugin-ecosystem="${PLUGIN_IMAGE}:${GITHUB_SHA}"' in source


def test_plugin_deployment_smoke_uses_canonical_operational_probes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "https://karen.ai/health/live" in source
    assert "https://karen.ai/ready" in source
    assert "https://karen.ai/api/health/system" not in source
    assert "https://karen.ai/api/health/plugins" not in source
