from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/ci/kui-local-acceptance.sh"
DEPLOY = ROOT / "scripts/ci/kui-card-studio-local-deployment.sh"
OVERLAY = ROOT / "deploy/compose/docker-compose.local-card-studio.yml"
VERIFY = ROOT / "scripts/ci/verify_local_card_studio_acceptance.py"
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/card-studio-live-acceptance.spec.ts"


def test_kcard_local_acceptance_has_explicit_fail_closed_guard():
    runner = RUNNER.read_text()
    assert "RUN_CARD_STUDIO_LOCAL:-0" in runner
    assert "KAREN_CARD_STUDIO_LOCAL_ACCEPTANCE_REQUIRED" in runner
    assert "KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE" in runner
    assert "KAREN_CARD_STUDIO_MUTATION_APPROVED" in runner
    assert "KAREN_UX_ISOLATION_EMAIL" in runner
    assert "KAREN_UX_ISOLATION_PASSWORD" in runner
    assert "VERCEL_AUTOMATION_BYPASS_SECRET" in runner
    assert "KAREN_SETTINGS_VERIFIED_DEPLOYMENT" in runner
    assert "card-studio-live-acceptance.spec.ts" in runner


def test_kcard_browser_evidence_requires_exact_three_passes():
    runner = RUNNER.read_text()
    assert 'stats.get("expected") != 3' in runner
    assert 'for key in ("unexpected", "skipped", "flaky")' in runner
    assert '"KCARD-LIVE-MUTATION:"' in runner
    assert '"KCARD-LIVE-ISOLATION:"' in runner
    assert "--retries=0" in runner


def test_kcard_local_deployment_overlay_is_loopback_and_disposable():
    overlay = OVERLAY.read_text()
    deploy = DEPLOY.read_text()
    assert "127.0.0.1:${KCARD_API_PORT:-8000}:8000" in overlay
    assert "127.0.0.1:${KCARD_WEB_PORT:-8010}:8010" in overlay
    assert 'KARI_ENABLE_CARD_STUDIO_CRUD: "true"' in overlay
    assert 'AUTH_ALLOW_DEV_LOGIN: "false"' in overlay
    assert 'KARI_AUTH_BYPASS: "false"' in overlay
    assert "COMPOSE_PROJECT_NAME" in deploy
    assert "docker compose" in deploy
    assert "deploy/compose/docker-compose.prod.yml" in deploy
    assert "deploy/compose/docker-compose.local-card-studio.yml" in deploy
    assert "host.docker.internal" in overlay
    assert '${KCARD_DB_PORT:?KCARD_DB_PORT is required}' in overlay
    assert "54322" not in overlay
    assert "postgres:" not in overlay


def test_kcard_provenance_fails_closed_for_sha_and_security_flags():
    verifier = VERIFY.read_text()
    assert "Incorrect source SHA" in verifier
    assert "Loopback" not in verifier or "loopback" in verifier
    assert "KARI_ENABLE_CARD_STUDIO_CRUD=true" in verifier
    assert "AUTH_ALLOW_DEV_LOGIN=false" in verifier
    assert "KARI_AUTH_BYPASS=false" in verifier
    assert "AUTH_ENABLE_SESSION_VALIDATION=true" in verifier
    assert 'revision != {"status": "ok", "revision": args.sha}' in verifier


def test_kcard_spec_local_guard_and_existing_three_scenarios():
    spec = SPEC.read_text()
    assert 'const localRequired = process.env.KAREN_CARD_STUDIO_LOCAL_ACCEPTANCE_REQUIRED === "true";' in spec
    assert "Vercel deployment" in spec
    assert 'test("KCARD-LIVE:' in spec
    assert 'test("KCARD-LIVE-MUTATION:' in spec
    assert 'test("KCARD-LIVE-ISOLATION:' in spec


def test_kcard_negative_local_provenance_cases_fail_closed():
    from scripts.ci.verify_local_card_studio_acceptance import GuardError, loopback_origin

    for raw in (
        "https://127.0.0.1:8010",
        "http://example.com:8010",
        "http://127.0.0.1:8010/other",
        "http://user@127.0.0.1:8010",
    ):
        try:
            loopback_origin(raw)
        except GuardError:
            pass
        else:
            raise AssertionError(f"Unsafe origin accepted: {raw}")

    assert loopback_origin("http://127.0.0.1:8010") == "http://127.0.0.1:8010"


def test_disposable_provisioning_generates_all_compose_inputs_without_real_docker(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys

    import pytest

    subprocess.run(["bash", "-n", str(DEPLOY)], check=True)
    body = DEPLOY.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    code = compile(body, str(DEPLOY), "exec")
    sha = "a" * 40
    database = "kcard_" + sha[:12]
    output = tmp_path / "output"
    output.mkdir()
    env_file = output / ".env.production"
    port = 54342
    (tmp_path / ".env").write_text(f"DB_HOST=localhost\nDB_PORT={port}\nDB_PASSWORD=fixture-secret\n")
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "config.toml").write_text(
        f'project_id = "fixture"\n[db]\nport = {port}\n'
    )
    (tmp_path / "supabase" / "migrations" / "001.sql").write_text("SELECT 1;")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["-", str(env_file), sha, database, str(output)])
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    calls = []
    existing = False

    def execute(args, **kwargs):
        calls.append(args)
        if args == ["docker", "context", "inspect"]:
            stdout = json.dumps([{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}])
        elif args == ["docker", "inspect", "supabase_db_fixture"]:
            stdout = json.dumps([{
                "Name": "/supabase_db_fixture", "Id": "b" * 64, "State": {"Running": True},
                "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": str(port)}]}},
            }])
        elif "SELECT 1 FROM pg_database" in args[-1]:
            stdout = "1\n" if existing else ""
        elif "createdb" in args or args[:3] == ["docker", "exec", "-i"]:
            stdout = ""
        else:
            raise AssertionError("Unexpected Docker invocation")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", execute)
    exec(code, {})
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    for key in ("DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL"):
        assert values[key] == values["KCARD_" + key]
        assert values[key].endswith(f":{port}/" + database)
    assert values["KCARD_DB_PORT"] == str(port)
    keys = ("SECRET_KEY", "AUTH_SECRET_KEY", "AUTH_JWT_SECRET_KEY", "REDIS_PASSWORD",
            "EXTENSION_SECRET_KEY", "EXTENSION_API_KEY", "GRAFANA_ADMIN_PASSWORD")
    assert len({values[key] for key in keys}) == len(keys)
    assert all(len(values[key]) == 64 for key in keys)
    assert sum("createdb" in args for args in calls) == 1
    assert sum(args[:3] == ["docker", "exec", "-i"] for args in calls) == 1

    calls.clear()
    (tmp_path / ".env").write_text("DB_HOST=localhost\nDB_PORT=54322\nDB_PASSWORD=fixture-secret\n")
    with pytest.raises(SystemExit, match="canonical configured"):
        exec(code, {})
    assert calls == []
    (tmp_path / ".env").write_text(f"DB_HOST=localhost\nDB_PORT={port}\nDB_PASSWORD=fixture-secret\n")
    calls.clear()
    existing = True
    with pytest.raises(SystemExit, match="already exists"):
        exec(code, {})
    assert not any("createdb" in args or args[:3] == ["docker", "exec", "-i"] for args in calls)

    calls.clear()
    monkeypatch.setenv("DOCKER_HOST", "tcp://example.invalid:2375")
    with pytest.raises(SystemExit, match="endpoint overrides"):
        exec(code, {})
    assert calls == []
