"""Retired DuckDB must not gate KAREN startup or reappear in deployment wiring.

This test protects the active ingress and Compose configuration without
modifying PostgreSQL/Redis, cryptographic key checks or migration history.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER_CONFIG = ROOT / "src/ai_karen_engine/server/config.py"
COMPOSE = ROOT / "docker-compose.yml"
REQUIREMENTS = ROOT / "requirements.txt"


def _required_environment_keys() -> set[str]:
    source = SERVER_CONFIG.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER_CONFIG))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "required_env_vars"
            for target in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("Canonical production environment validation was removed")


def test_retired_database_cannot_block_production_startup() -> None:
    required = _required_environment_keys()
    assert "KARI_DUCKDB_PASSWORD" not in required
    # Preserve currently required durable DB, bounded state, and security gates.
    assert {
        "DATABASE_URL",
        "POSTGRES_URL",
        "AUTH_DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "AUTH_SECRET_KEY",
        "KARI_JOB_ENC_KEY",
        "KARI_JOB_SIGNING_KEY",
        "KARI_MODEL_SIGNING_KEY",
        "EXTENSION_SECRET_KEY",
        "EXTENSION_API_KEY",
    } <= required


def test_active_compose_does_not_enable_retired_database() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "KARI_ENABLE_DUCKDB" not in compose
    assert "KARI_DUCKDB_PASSWORD" not in compose
    assert 'DATABASE_URL: "${DATABASE_URL:' in compose
    assert 'POSTGRES_URL: "${POSTGRES_URL:' in compose
    assert 'AUTH_DATABASE_URL: "${AUTH_DATABASE_URL:' in compose
    assert 'REDIS_URL: "redis://:' in compose


def test_runtime_requirements_do_not_reinstall_retired_database() -> None:
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    active = [
        line.split("#", 1)[0].strip()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(re.match(r"(?i)^duckdb(?:\\s|[=<>!~;\\[]|$)", line) for line in active)
    assert any(re.match(r"(?i)^redis(?:\\s|[=<>!~;\\[]|$)", line) for line in active)
