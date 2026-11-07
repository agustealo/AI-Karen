"""Read-only local status reports backend truth, never a hardcoded model."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "scripts/dev/status.sh"


def _run(tmp_path: Path, *, first_run: str = '{"first_run_required":false}',
         api_live: bool = True, first_run_ok: bool = True,
         web_live: bool = True, api_origin: str | None = None,
         backend_payload: str = '{"status":"ok","backend_ready":true}',
         backend_ok: bool = True) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    root = tmp_path / "local"
    root.mkdir()
    script = root / "status.sh"
    shutil.copy2(STATUS, script)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    events = tmp_path / "events.log"
    curl = bindir / "curl"
    curl.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$*" >> "$KAREN_TEST_EVENTS"\n'
        'case "$*" in\n'
        ' *"/health/live"*) [ "$KAREN_TEST_API_LIVE" = 1 ]; exit $?;;\n'
        ' *"/api/auth/first-run"*) [ "$KAREN_TEST_FIRST_RUN_OK" = 1 ] || exit 22;'
        ' printf "%s" "$KAREN_TEST_FIRST_RUN_JSON"; exit 0;;\n'
        ' *"/api/health"*) [ "$KAREN_TEST_BACKEND_OK" = 1 ] || exit 22;'
        ' printf "%s" "$KAREN_TEST_BACKEND_JSON"; exit 0;;\n'
        ' *"8010/"*) [ "$KAREN_TEST_WEB_LIVE" = 1 ]; exit $?;;\n'
        ' *) exit 22;;\n'
        'esac\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "KAREN_TEST_EVENTS": str(events),
        "KAREN_TEST_API_LIVE": "1" if api_live else "0",
        "KAREN_TEST_FIRST_RUN_OK": "1" if first_run_ok else "0",
        "KAREN_TEST_WEB_LIVE": "1" if web_live else "0",
        "KAREN_TEST_FIRST_RUN_JSON": first_run,
        "KAREN_TEST_BACKEND_JSON": backend_payload,
        "KAREN_TEST_BACKEND_OK": "1" if backend_ok else "0",
    }
    if api_origin is not None:
        env["KAREN_LOCAL_API_ORIGIN"] = api_origin
    else:
        env.pop("KAREN_LOCAL_API_ORIGIN", None)
    env.pop("KAREN_LOCAL_WEB_ORIGIN", None)
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True,
        env=env, cwd=root, timeout=10, check=False,
    )
    return result, events.read_text(encoding="utf-8").splitlines() if events.exists() else []


@pytest.mark.parametrize(("response", "expected"), [
    ('{"first_run_required":false}', "CONFIGURED"),
    ('{"first_run_required":true}', "BOOTSTRAP_REQUIRED"),
])
def test_status_uses_canonical_boolean_first_run_state(tmp_path: Path, response: str, expected: str):
    result, events = _run(tmp_path, first_run=response)
    assert result.returncode == 0, result.stderr
    assert f"First-run state: {expected}" in result.stdout
    assert "Canonical backend readiness: VERIFIED" in result.stdout
    assert "Model generation: UNVERIFIED" in result.stdout
    assert "CopilotKit first turn/replay: UNVERIFIED" in result.stdout
    assert len(events) == 4
    assert all("Authorization" not in entry for entry in events)


@pytest.mark.parametrize("response", [
    "{}", '{"first_run_required":"false"}', '{"first_run_required":0}',
    '{"first_run_required":null}', "not-json", "[]",
])
def test_bad_auth_state_never_claims_readiness(tmp_path: Path, response: str):
    result, events = _run(tmp_path, first_run=response)
    assert result.returncode == 1
    assert "First-run state: UNAVAILABLE" in result.stdout
    assert len(events) == 2


def test_unreachable_api_does_not_guess_first_run_or_model(tmp_path: Path):
    result, events = _run(tmp_path, api_live=False)
    assert result.returncode == 1
    assert "API liveness: UNAVAILABLE" in result.stdout
    assert "First-run state: UNVERIFIED" in result.stdout
    assert "Model generation: UNVERIFIED" in result.stdout
    assert len(events) == 1


def test_web_downtime_does_not_fabricate_chat_or_hide_api_state(tmp_path: Path):
    result, _ = _run(tmp_path, web_live=False)
    assert result.returncode == 1
    assert "Web ingress: UNAVAILABLE" in result.stdout
    assert "First-run state: CONFIGURED" in result.stdout
    assert "CopilotKit first turn/replay: UNVERIFIED" in result.stdout


@pytest.mark.parametrize("origin", [
    "http://example.com:8000", "https://localhost:8000",
    "http://127.0.0.1:8000/private", "http://user:secret@localhost:8000",
    "http://localhost:65536", "http://localhost:8000?secret=yes",
])
def test_only_safe_loopback_origin_allowed(tmp_path: Path, origin: str):
    result, events = _run(tmp_path, api_origin=origin)
    assert result.returncode == 2
    assert "secret" not in result.stderr
    assert events == []


def test_status_has_no_fake_model_or_outdated_commands():
    text = STATUS.read_text(encoding="utf-8")
    assert "local-gguf" not in text
    assert "nvidia-smi" not in text
    assert "docker compose down" not in text
    assert '"/health/live"' not in text or "/health/live" in text
    assert "first_run_required" in text



@pytest.mark.parametrize("payload", [
    '{"status":"initializing","backend_ready":false}',
    '{"status":"ok","backend_ready":"true"}',
    '{"status":"ok"}',
    '{"backend_ready":true}',
    '{"status":"ok","backend_ready":true,"unknown":"untrusted"}',
    "not-json",
    "[]",
])
def test_unverified_canonical_backend_fails_status(
    tmp_path: Path, payload: str,
) -> None:
    result, events = _run(tmp_path, backend_payload=payload)
    assert result.returncode == 1
    assert "First-run state: CONFIGURED" in result.stdout
    assert "Web ingress: REACHABLE" in result.stdout
    assert "Canonical backend readiness: UNAVAILABLE" in result.stdout
    assert "Model generation: UNVERIFIED" in result.stdout
    assert len(events) == 4


def test_unreachable_consumer_backend_fails_without_response_leak(tmp_path: Path) -> None:
    result, events = _run(tmp_path, backend_ok=False)
    assert result.returncode == 1
    assert "Canonical backend readiness: UNAVAILABLE" in result.stdout
    assert "CopilotKit first turn/replay: UNVERIFIED" in result.stdout
    assert len(events) == 4
