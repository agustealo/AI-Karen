"""Source-only contract for canonical Supabase identity across local Compose."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/dev/verify_local_db_config.py"
COMPOSE = ROOT / "docker-compose.yml"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("local_db_config_test", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(**overrides):
    env = {
        "DATABASE_URL": "postgresql://user:p%40ss@host.docker.internal:54322/postgres",
        "POSTGRES_URL": "postgresql+asyncpg://user:p%40ss@host.docker.internal:54322/postgres",
        "AUTH_DATABASE_URL": "postgresql+asyncpg://user:p%40ss@host.docker.internal:54322/postgres",
        "DB_HOST": "host.docker.internal",
        "DB_PORT": "54322",
        "DB_USER": "user",
        "DB_PASSWORD": "p@ss",
        "DB_NAME": "postgres",
    }
    env.update(overrides)
    return {"services": {"redis": {}, "api": {"environment": env}, "web": {}}}


def test_one_effective_supabase_identity_accepts_percent_encoded_password(module):
    module.verify(config())


@pytest.mark.parametrize(("key", "value"), [
    ("POSTGRES_URL", "postgresql+asyncpg://user:p%40ss@another.example:54322/postgres"),
    ("AUTH_DATABASE_URL", "postgresql+asyncpg://user:p%40ss@host.docker.internal:54322/foreign"),
    ("DB_HOST", "another.example"),
    ("DB_PASSWORD", "wrong"),
    ("DB_PORT", "54323"),
    ("DB_USER", "wrong"),
    ("DB_NAME", "wrong"),
])
def test_mismatched_identity_fails_closed_without_reflecting_values(module, key, value):
    with pytest.raises(module.ConfigError) as caught:
        module.verify(config(**{key: value}))
    assert value not in str(caught.value)
    assert "p@ss" not in str(caught.value)


@pytest.mark.parametrize("bad", [
    "postgresql://user:p%40ss@localhost:54322/postgres",
    "postgresql://user:p%40ss@127.0.0.1:54322/postgres",
    "postgresql://user:p%40ss@postgres:5432/postgres",
    "postgresql://user:p%40ss@host.docker.internal:bad/postgres",
    "https://user:p%40ss@host.docker.internal:54322/postgres",
    "postgresql://user:p%40ss@host.docker.internal:54322/postgres#hidden",
])
def test_invalid_local_database_url_is_rejected(module, bad):
    with pytest.raises(module.ConfigError):
        module.verify(config(DATABASE_URL=bad))


@pytest.mark.parametrize("bad", [
    {}, {"services": {}}, {"services": {"api": {}}},
    {"services": {"postgres": {}, "redis": {}, "api": {}, "web": {}}},
])
def test_unknown_stack_cannot_claim_canonical_supabase(module, bad):
    with pytest.raises(module.ConfigError):
        module.verify(bad)


def test_docker_compose_uses_explicit_operator_configuration_not_fixed_passwords():
    content = COMPOSE.read_text(encoding="utf-8")
    for key in ("DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL",
                "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        assert key + ': "' + chr(36) + '{' + key + ':?' in content
    assert "postgresql://postgres:postgres@host.docker.internal:54322/postgres" not in content
    launcher = (ROOT / "scripts/dev/start_docker_services.sh").read_text(encoding="utf-8")
    assert "docker compose -f docker-compose.yml config --format json" in launcher
    assert "python3 scripts/dev/verify_local_db_config.py" in launcher
    assert launcher.index("verify_local_db_config.py") < launcher.index(" up -d --wait redis")


def test_validator_emits_generic_failure_without_private_values(module, monkeypatch, capsys):
    import io

    bad = config(DB_PASSWORD="private-secret")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(bad)))
    assert module.main() == 1
    captured = capsys.readouterr()
    assert "private-secret" not in captured.err
    assert "host.docker.internal" not in captured.err
    assert "database identity" in captured.err.lower()

