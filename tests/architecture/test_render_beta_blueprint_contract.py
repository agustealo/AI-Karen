"""Guard the existing Render beta Blueprint against stale branch or secret drift.

The canonical list of production-required environment names belongs to
ai_karen_engine.server.config. This test reads that source without importing
production settings, starting a model, or provisioning infrastructure.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "src/ai_karen_engine/server/config.py"
BLUEPRINT = ROOT / "deploy/render/render.yaml"


def _required_runtime_names() -> set[str]:
    module = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "required_env_vars"
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Dict), "Runtime env manifest must remain a dictionary"
        names: list[str] = []
        for key in node.value.keys:
            assert isinstance(key, ast.Constant) and isinstance(key.value, str)
            names.append(key.value)
        assert len(names) == len(set(names)), "Duplicate runtime environment authority"
        assert names, "Production runtime must declare required environment variables"
        return set(names)
    raise AssertionError("Canonical runtime required_env_vars manifest was not found")


def _env_blocks() -> dict[str, str]:
    source = BLUEPRINT.read_text(encoding="utf-8")
    matches = list(
        re.finditer(r"^      - key: ([A-Z0-9_]+)\s*$", source, flags=re.MULTILINE)
    )
    names = [match.group(1) for match in matches]
    assert len(names) == len(set(names)), "Duplicate environment keys in Render Blueprint"
    return {
        match.group(1): source[match.end():matches[index + 1].start()]
        if index + 1 < len(matches)
        else source[match.end():]
        for index, match in enumerate(matches)
    }


def test_render_service_tracks_reviewed_main_and_requires_health() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")
    assert len(re.findall(r"^    name: ai-karen-beta-api$", source, flags=re.MULTILINE)) == 1
    assert re.search(r"^    branch: main$", source, flags=re.MULTILINE)
    assert "feat/chat-consumer-conversation-management-20261031" not in source
    assert re.search(r"^    autoDeployTrigger: off$", source, flags=re.MULTILINE)
    assert re.search(r"^    healthCheckPath: /health/live$", source, flags=re.MULTILINE)
    assert re.search(r"^    runtime: docker$", source, flags=re.MULTILINE)


def test_render_blueprint_covers_every_canonical_production_required_key() -> None:
    blocks = _env_blocks()
    required = _required_runtime_names()
    assert required.issubset(blocks), (
        "Render Blueprint does not provide canonical runtime environment keys: "
        + ", ".join(sorted(required.difference(blocks)))
    )


def test_existing_database_and_redis_are_reused_without_duplicate_instances() -> None:
    source = BLUEPRINT.read_text(encoding="utf-8")
    blocks = _env_blocks()
    assert "fromDatabase:" in blocks["DATABASE_URL"]
    assert "name: ai-karen-beta-postgres" in blocks["DATABASE_URL"]
    assert "property: connectionString" in blocks["DATABASE_URL"]
    assert "fromService:" in blocks["REDIS_URL"]
    assert "name: ai-karen-beta-redis" in blocks["REDIS_URL"]
    assert "type: keyvalue" in blocks["REDIS_URL"]
    assert not re.search(r"^databases:", source, flags=re.MULTILINE)
    assert not re.search(r"^  - type: keyvalue$", source, flags=re.MULTILINE)


def test_format_sensitive_keys_require_explicit_secure_configuration() -> None:
    blocks = _env_blocks()
    for key in ("POSTGRES_URL", "AUTH_DATABASE_URL", "KARI_JOB_ENC_KEY", "KARI_CORS_ORIGINS"):
        assert re.search(r"^        sync: false$", blocks[key], flags=re.MULTILINE), key
        assert "generateValue:" not in blocks[key], key

    for key in (
        "SECRET_KEY",
        "AUTH_SECRET_KEY",
        "EXTENSION_SECRET_KEY",
        "EXTENSION_API_KEY",
        "KARI_DUCKDB_PASSWORD",
        "KARI_JOB_SIGNING_KEY",
        "KARI_MODEL_SIGNING_KEY",
    ):
        assert "generateValue: true" in blocks[key], key

    for key in (
        "AUTH_DEV_MODE",
        "AUTH_ALLOW_DEV_LOGIN",
        "KARI_AUTH_BYPASS",
        "EXTENSION_DEV_BYPASS_ENABLED",
    ):
        assert re.search(r"^        value: \"false\"$", blocks[key], flags=re.MULTILINE), key
