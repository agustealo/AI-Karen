"""Local Compose launcher never manages secrets, shadows schema, or tears down a stack."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/dev/start_docker_services.sh"
JSON_BACKEND_READY = '{"status":"ok","backend_ready":true}'


def _invoke(tmp_path: Path, *, config_status: int = 0, first_run_status: int = 0,
            with_env: bool = True, first_run_payload: str = '{"first_run_required":false}',
            web_status: int = 0) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    root = tmp_path / "checkout"
    script = root / "scripts/dev/start_docker_services.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(LAUNCHER, script)
    shutil.copy2(ROOT / "scripts/dev/status.sh", script.parent / "status.sh")
    shutil.copy2(ROOT / "scripts/dev/verify_local_db_config.py", script.parent / "verify_local_db_config.py")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    if with_env:
        (root / ".env").write_text("REDIS_PASSWORD=provided-by-operator\n", encoding="utf-8")
        (root / ".env.local").write_text("# local web vars\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events.log"
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "docker %s\\n" "$*" >> "$KAREN_TEST_EVENTS"\n'
        'case " $* " in *" config --quiet "*) exit "$KAREN_TEST_CONFIG_EXIT";;\n' +
        '  *" config --format json "*) printf \'%s\' \'{"services":{"redis":{},"web":{},"api":{"environment":{"DATABASE_URL":"postgresql://test:pass@host.docker.internal:54322/postgres","POSTGRES_URL":"postgresql+asyncpg://test:pass@host.docker.internal:54322/postgres","AUTH_DATABASE_URL":"postgresql+asyncpg://test:pass@host.docker.internal:54322/postgres","DB_HOST":"host.docker.internal","DB_PORT":"54322","DB_USER":"test","DB_PASSWORD":"pass","DB_NAME":"postgres"}}}}\';; esac\n'
        'exit 0\n', encoding="utf-8",
    )
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf "curl %s\\n" "$*" >> "$KAREN_TEST_EVENTS"\n'
        'case " $* " in\n'
        '  *"/api/auth/first-run"*) [ "$KAREN_TEST_FIRST_RUN_EXIT" = 0 ] || exit "$KAREN_TEST_FIRST_RUN_EXIT"; printf "%s" "$KAREN_TEST_FIRST_RUN_PAYLOAD"; exit 0;;\n'
        '  *"/api/health"*) printf "%s" "$KAREN_TEST_BACKEND_PAYLOAD"; exit 0;;\n'
        '  *"8010/"*) exit "$KAREN_TEST_WEB_EXIT";;\n'
        'esac\n'
        'exit 0\n', encoding="utf-8",
    )
    docker.chmod(0o755)
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "KAREN_TEST_EVENTS": str(events),
        "KAREN_TEST_CONFIG_EXIT": str(config_status),
        "KAREN_TEST_FIRST_RUN_EXIT": str(first_run_status),
        "KAREN_TEST_FIRST_RUN_PAYLOAD": first_run_payload,
        "KAREN_TEST_WEB_EXIT": str(web_status),
        "KAREN_TEST_BACKEND_PAYLOAD": JSON_BACKEND_READY,
        "KAREN_LOCAL_API_ORIGIN": "http://127.0.0.1:8000",
        "KAREN_LOCAL_WEB_ORIGIN": "http://127.0.0.1:8010",
    }
    result = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, env=env,
        text=True, capture_output=True, timeout=10, check=False,
    )
    return result, events.read_text(encoding="utf-8").splitlines() if events.exists() else []


def test_launch_is_nondestructive_and_uses_only_canonical_services(tmp_path: Path) -> None:
    result, calls = _invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls[:4] == [
        "docker compose -f docker-compose.yml config --quiet",
        "docker compose -f docker-compose.yml config --format json",
        "docker compose -f docker-compose.yml up -d --wait redis",
        "docker compose -f docker-compose.yml up -d --wait api web",
    ]
    assert len([x for x in calls if x.startswith("curl ")]) == 4
    assert not any("down" in x or "postgres" in x or "minio" in x for x in calls)
    assert "CopilotKit first turn/replay: UNVERIFIED" in result.stdout
    assert "First-run state: CONFIGURED" in result.stdout
    assert "Canonical backend readiness: VERIFIED" in result.stdout


@pytest.mark.parametrize("with_env,config_status", [(False, 0), (True, 1)])
def test_failure_occurs_before_stack_mutation(
    tmp_path: Path, with_env: bool, config_status: int,
) -> None:
    result, calls = _invoke(tmp_path, with_env=with_env, config_status=config_status)
    assert result.returncode != 0
    assert not any(" up " in c or " down " in c for c in calls)


def test_failed_first_run_is_not_reported_as_success(tmp_path: Path) -> None:
    result, calls = _invoke(tmp_path, first_run_status=22)
    assert result.returncode != 0
    assert "Local runtime is not ready" in result.stderr
    assert len([x for x in calls if x.startswith("curl ")]) == 2


def test_launcher_contains_no_embedded_secret_values_or_destructive_actions() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'docker compose -f docker-compose.yml config --quiet' in source
    assert "docker compose down" not in source
    assert "export REDIS_PASSWORD=" not in source
    assert "export POSTGRES_PASSWORD=" not in source
    assert "KARI_AUTH_BYPASS" not in source
    assert "--wait api web" in source
    assert "verify_local_db_config.py" in source
    assert "bash scripts/dev/status.sh" in source
    assert "curl --fail" not in source


@pytest.mark.parametrize("payload", [
    '{}', '{"first_run_required":"false"}', 'not-json', '[]',
])
def test_invalid_first_run_contract_never_claims_booted_runtime(
    tmp_path: Path, payload: str,
) -> None:
    result, calls = _invoke(tmp_path, first_run_payload=payload)
    assert result.returncode != 0
    assert "First-run state: UNAVAILABLE" in result.stdout
    assert "Local Compose ingress validated" not in result.stdout
    assert len([x for x in calls if x.startswith("curl ")]) == 2


def test_missing_web_ingress_fails_launcher_after_valid_api(tmp_path: Path) -> None:
    result, calls = _invoke(tmp_path, web_status=22)
    assert result.returncode != 0
    assert "Web ingress: UNAVAILABLE" in result.stdout
    assert "Local runtime is not ready" in result.stderr
    assert len([x for x in calls if x.startswith("curl ")]) == 3


def test_first_run_setup_needed_is_reported_not_automatically_completed(tmp_path: Path) -> None:
    result, _ = _invoke(tmp_path, first_run_payload='{"first_run_required":true}')
    assert result.returncode == 0
    assert "First-run state: BOOTSTRAP_REQUIRED" in result.stdout
    assert "Model generation: UNVERIFIED" in result.stdout
