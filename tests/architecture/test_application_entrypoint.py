from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
CLI_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "cli.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_canonical_application_entrypoint_exists() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "def create_app()" in source
    assert "from server import app as legacy_app" in source
    assert "return legacy_app.app" in source
    assert "sys.path" not in source


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
