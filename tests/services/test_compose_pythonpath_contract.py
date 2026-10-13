"""Compose must not depend on the caller's ambient PYTHONPATH."""

from pathlib import Path


def test_api_compose_pythonpath_does_not_interpolate_host_environment():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert 'PYTHONPATH: "/app:/app/src"' in compose
    assert "$PYTHONPATH" not in compose
