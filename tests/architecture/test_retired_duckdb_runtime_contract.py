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
    assert not any(line.lower().split("=", 1)[0].split("[", 1)[0].strip().startswith("duckdb") for line in active)
    assert any(line.lower().split("=", 1)[0].strip() == "redis" for line in active)


def test_no_live_duckdb_imports_or_flags_in_runtime_sources() -> None:
    """Guard every first-party runtime source, not just the known entry points."""
    roots = (
        ROOT / "src/ai_karen_engine",
        ROOT / "src/api",
        ROOT / "scripts/ci",
        ROOT / "scripts/deploy",
        ROOT / "deploy/render",
    )
    source_suffixes = {".py", ".js", ".ts", ".tsx", ".sh", ".yaml", ".yml", ".toml"}
    retired_code_patterns = (
        re.compile(r"(?i)\bimport\s+duckdb\b"),
        re.compile(r"(?i)\bfrom\s+duckdb\s+import\b"),
        re.compile(r"(?i)\bduckdb\s*\.\s*connect\s*\("),
        re.compile(r"\bKARI_DUCKDB_PASSWORD\b"),
        re.compile(r"\bKARI_ENABLE_DUCKDB\b"),
    )
    violations: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file() or candidate.suffix not in source_suffixes:
                continue
            if any(part in {"node_modules", "__pycache__", "venv", ".venv"} for part in candidate.parts):
                continue
            source = candidate.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(source.splitlines(), 1):
                if any(pattern.search(line) for pattern in retired_code_patterns):
                    violations.append(f"{candidate.relative_to(ROOT)}:{lineno}")
    assert not violations, "Retired database still wired in source: " + ", ".join(violations)


def test_render_blueprint_and_secret_inspector_drop_retired_database() -> None:
    blueprint = (ROOT / "deploy/render/render.yaml").read_text(encoding="utf-8")
    inspector = (ROOT / "scripts/deploy/inspect_render_beta_environment.py").read_text(encoding="utf-8")
    assert "KARI_DUCKDB_PASSWORD" not in blueprint
    assert "KARI_ENABLE_DUCKDB" not in blueprint
    assert "KARI_DUCKDB_PASSWORD" not in inspector
    for required in ("DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL", "REDIS_URL", "KARI_JOB_ENC_KEY"):
        assert required in blueprint
