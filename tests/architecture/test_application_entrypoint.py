from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
LEGACY_SERVER_APP = REPO_ROOT / "server" / "app.py"
CLI_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "cli.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_canonical_application_entrypoint_constructs_fastapi_directly() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "def create_app()" in source
    assert "app = FastAPI(" in source
    assert "create_application_lifespan(settings)" in source
    assert "wire_routers(app, settings)" in source
    assert "from server import app as legacy_app" not in source
    assert "legacy_app.app" not in source
    assert "sys.path" not in source


def test_legacy_server_app_is_compatibility_only() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    assert "from ai_karen_engine.app import create_app" in source
    assert "app = create_app()" in source
    assert "FastAPI(" not in source
    assert "wire_routers(" not in source
    assert "create_application_lifespan" not in source
    assert "@app.on_event" not in source


def test_operator_cli_targets_canonical_application() -> None:
    source = CLI_ENTRYPOINT.read_text(encoding="utf-8")

    assert 'APP_TARGET = "ai_karen_engine.app:create_app"' in source
    assert '"--factory"' in source
    assert "server.app" not in source
    assert "server.run" not in source
    assert "sys.path.insert" not in source


def test_docker_runs_canonical_asgi_entrypoint_directly() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert '"ai_karen_engine.app:create_app"' in source
    assert '"--factory"' in source
    assert 'CMD ["python", "start.py"]' not in source
    assert "EXPOSE 8000 9090" not in source


def test_retired_startup_layers_do_not_reappear() -> None:
    assert not (REPO_ROOT / "start.py").exists()
    assert not (REPO_ROOT / "server" / "run.py").exists()


def test_docker_does_not_install_unused_poetry_launcher_dependency() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "pip install --no-cache-dir poetry" not in source
    assert "setuptools wheel poetry" not in source
