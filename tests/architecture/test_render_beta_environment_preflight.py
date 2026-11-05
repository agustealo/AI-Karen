"""Adversarial read-only Render environment recovery tests."""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts/deploy"
SERVICE = "srv-dbjmh78u01pc73ftse40"
WORKSPACE = "tea-dbjm53o473hc73a8s5ng"
POSTGRES = "dpg-dbjme1tg1s2s7385svhg-a"
KV = "red-dbjme2ijnfac738ehstg"
DATABASE_URL = "postgresql://testuser:testpassword@dpg-private-a/db"
REDIS_URL = "redis://red-private:6379"


@pytest.fixture
def m():
    sys.path.insert(0, str(SCRIPT_DIR))
    name = "render_beta_environment_preflight"
    spec = importlib.util.spec_from_file_location(
        name, SCRIPT_DIR / "inspect_render_beta_environment.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def safe_env(m):
    env = {name: "R" * 48 for name in m.required_environment_defaults(m.SERVER_CONFIG)}
    env.update({name: "S" * 48 for name in m.PROTECTED_SECRETS})
    env.update({
        "KARI_JOB_ENC_KEY": base64.urlsafe_b64encode(b"x" * 32).decode(),
        "DATABASE_URL": DATABASE_URL,
        "POSTGRES_URL": DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        "AUTH_DATABASE_URL": DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        "REDIS_URL": REDIS_URL,
        "KARI_CORS_ORIGINS": "https://ai-karen.example.com",
        "ENVIRONMENT": "production", "AUTH_MODE": "production",
        "EXTENSION_REQUIRE_HTTPS": "true",
    })
    for name in m.SAFE_FLAGS:
        env[name] = "false"
    return env


class FakeClient:
    def __init__(self, env, *, branch="main", health="/health/live",
                 links=None, owner=WORKSPACE):
        self.env = env
        self.branch = branch
        self.health = health
        self.links = links or []
        self.owner = owner
        self.calls = []

    def get(self, service_id):
        self.calls.append(("GET", "service", service_id))
        return {
            "id": SERVICE, "ownerId": WORKSPACE, "name": "ai-karen-beta-api",
            "repo": "https://github.com/agustealo/AI-Karen",
            "type": "web_service", "branch": self.branch, "autoDeployTrigger": "off",
            "serviceDetails": {
                "region": "ohio", "healthCheckPath": self.health, "plan": "free",
            },
        }

    def inspect_resource(self, kind, resource_id):
        self.calls.append(("GET", kind, resource_id))
        if kind == "postgres":
            return {
                "id": POSTGRES, "owner": {"id": self.owner},
                "name": "ai-karen-beta-postgres", "region": "ohio",
                "status": "available", "plan": "free",
                "expiresAt": "2026-12-01T16:21:27Z",
            }
        assert kind == "key-value"
        return {
            "id": KV, "owner": {"id": WORKSPACE}, "name": "ai-karen-beta-redis",
            "region": "ohio", "status": "available", "plan": "free",
        }

    def inspect_env_groups(self, workspace_id):
        self.calls.append(("GET", "env-groups", workspace_id))
        return self.links

    def inspect_env_vars(self, service_id):
        self.calls.append(("GET", "env-vars", service_id))
        return [
            {"envVar": {"key": key, "value": value}, "cursor": key}
            for key, value in self.env.items()
        ]

    def _request_path(self, endpoint, *, method):
        self.calls.append((method, endpoint))
        assert method == "GET"
        if endpoint == f"/v1/postgres/{POSTGRES}/connection-info":
            return {
                "internalConnectionString": DATABASE_URL,
                "externalConnectionString": "postgresql://public.example.com/not-used",
            }
        assert endpoint == f"/v1/key-value/{KV}/connection-info"
        return {"internalConnectionString": REDIS_URL}


def inspect(m, client):
    return m.inspect(
        client=client, service_id=SERVICE, workspace_id=WORKSPACE,
        postgres_id=POSTGRES, key_value_id=KV,
        manifest=m.Manifest.read(m.BLUEPRINT),
        blueprint=m.BLUEPRINT.read_text(encoding="utf-8"),
        required_defaults=m.required_environment_defaults(m.SERVER_CONFIG),
    )


def test_reads_canonical_config_contract_without_production_import(m):
    defaults = m.required_environment_defaults(m.SERVER_CONFIG)
    assert {"KARI_JOB_ENC_KEY", "DATABASE_URL", "AUTH_DATABASE_URL",
            "POSTGRES_URL", "REDIS_URL", "EXTENSION_SECRET_KEY"} <= set(defaults)
    blueprint = m.BLUEPRINT.read_text(encoding="utf-8")
    assert m.reference_name(
        blueprint, key="DATABASE_URL", ref_kind="fromDatabase",
    ) == "ai-karen-beta-postgres"
    assert m.reference_name(
        blueprint, key="REDIS_URL", ref_kind="fromService",
    ) == "ai-karen-beta-redis"
    assert m.Manifest.read(m.BLUEPRINT).health_check_path == "/health/live"


def test_valid_existing_resources_and_env_are_read_only_and_secret_free(m):
    client = FakeClient(safe_env(m))
    result = inspect(m, client)
    assert result.ready
    assert result.failures == ()
    assert "production_persistence:postgres_free_plan" in result.advisories
    assert "production_persistence:postgres_expiration_present" in result.advisories
    assert {call[0] for call in client.calls} == {"GET"}
    assert "testpassword" not in repr(result)


def test_governed_history_readiness_is_explicit_and_never_inferred(m):
    # A bootable beta environment is not automatically a consumer-ready
    # CopilotKit deployment. The legacy preflight remains read-only and
    # separate from the explicit migration-gated history acceptance mode.
    configured = safe_env(m)
    initial = inspect(m, FakeClient(configured))
    assert initial.ready

    disabled = m.inspect(
        client=FakeClient(configured), service_id=SERVICE,
        workspace_id=WORKSPACE, postgres_id=POSTGRES, key_value_id=KV,
        manifest=m.Manifest.read(m.BLUEPRINT),
        blueprint=m.BLUEPRINT.read_text(encoding="utf-8"),
        required_defaults=m.required_environment_defaults(m.SERVER_CONFIG),
        require_governed_history=True,
    )
    assert not disabled.ready
    for key in m.GOVERNED_HISTORY_REQUIRED:
        assert f"disabled:{key}" in disabled.failures

    for key in m.GOVERNED_HISTORY_REQUIRED:
        configured[key] = "true"
    enabled = m.inspect(
        client=FakeClient(configured), service_id=SERVICE,
        workspace_id=WORKSPACE, postgres_id=POSTGRES, key_value_id=KV,
        manifest=m.Manifest.read(m.BLUEPRINT),
        blueprint=m.BLUEPRINT.read_text(encoding="utf-8"),
        required_defaults=m.required_environment_defaults(m.SERVER_CONFIG),
        require_governed_history=True,
    )
    assert enabled.ready
    assert enabled.failures == ()
    assert "testpassword" not in repr(enabled)


def test_event_journal_cannot_be_enabled_without_durable_history(m):
    configured = safe_env(m)
    configured[m.AG_UI_EVENT_JOURNAL] = "true"
    bad = inspect(m, FakeClient(configured))
    assert f"invalid:{m.AG_UI_EVENT_JOURNAL}" in bad.failures
    configured["KARI_ENABLE_AG_UI_BRIDGE"] = "true"
    configured["KARI_ENABLE_AG_UI_DURABLE_RUNS"] = "true"
    assert inspect(m, FakeClient(configured)).ready


def test_all_missing_names_detected_without_disclosing_values(m):
    report = inspect(m, FakeClient({}))
    assert not report.ready
    for key in ("SECRET_KEY", "KARI_JOB_ENC_KEY", "DATABASE_URL",
                "POSTGRES_URL", "AUTH_DATABASE_URL", "REDIS_URL",
                "KARI_CORS_ORIGINS", "AUTH_JWT_SECRET_KEY"):
        assert "missing:" + key in report.failures


@pytest.mark.parametrize("key", (
    "DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL", "REDIS_URL",
))
def test_wrong_database_connections_rejected(m, key):
    env = safe_env(m)
    env[key] = "postgresql://attacker:private@external.example.com/foreign"
    report = inspect(m, FakeClient(env))
    assert "mismatch:" + key in report.failures
    assert "attacker" not in repr(report)
    assert "private@external" not in repr(report)


def test_insecure_runtime_modes_are_reported(m):
    env = safe_env(m)
    env["KARI_AUTH_BYPASS"] = "true"
    env["ENVIRONMENT"] = "development"
    env["EXTENSION_REQUIRE_HTTPS"] = "false"
    report = inspect(m, FakeClient(env))
    assert {"insecure:KARI_AUTH_BYPASS", "insecure:ENVIRONMENT",
            "insecure:EXTENSION_REQUIRE_HTTPS"} <= set(report.failures)


@pytest.mark.parametrize("bad", (
    "example", "invalid-==", "change-me",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
))
def test_rejects_malformed_job_encryption_key(m, bad):
    env = safe_env(m)
    env["KARI_JOB_ENC_KEY"] = bad
    assert "invalid:KARI_JOB_ENC_KEY" in inspect(m, FakeClient(env)).failures


@pytest.mark.parametrize("bad", (
    "*", "http://ai-karen.example.com", "https://localhost:3000",
    "https://ai-karen.example.com/path", "https://*.example.com",
))
def test_rejects_insecure_cors_origins(m, bad):
    env = safe_env(m)
    env["KARI_CORS_ORIGINS"] = bad
    assert "insecure:KARI_CORS_ORIGINS" in inspect(m, FakeClient(env)).failures


def test_reports_both_live_branch_and_health_path_drift(m):
    report = inspect(m, FakeClient(
        safe_env(m),
        branch="feat/chat-consumer-conversation-management-20261031",
        health="",
    ))
    assert "drift:branch" in report.failures
    assert "drift:health_check" in report.failures


def test_prevents_cross_workspace_database_and_invisible_env_groups(m):
    with pytest.raises(m.ReconcileError, match="identity"):
        inspect(m, FakeClient(safe_env(m), owner="tea-foreign"))
    groups = [{"ownerId": WORKSPACE, "serviceLinks": [{"id": SERVICE}]}]
    with pytest.raises(m.ReconcileError, match="Linked environment groups"):
        inspect(m, FakeClient(safe_env(m), links=groups))


def test_rejects_duplicate_env_names_and_public_connection_urls(m):
    with pytest.raises(m.ReconcileError, match="ambiguous"):
        m._env_records([
            {"envVar": {"key": "SECRET_KEY", "value": "one"}},
            {"envVar": {"key": "SECRET_KEY", "value": "two"}},
        ])
    for kind, url in (
        ("postgres", "postgresql://u:p@public.example.com/db"),
        ("postgres", "postgresql://u:p@localhost/db"),
        ("postgres", "https://u:p@dpg-private/db"),
        ("redis", "redis://default:p@public.example.com:6379"),
    ):
        with pytest.raises(m.ReconcileError, match="private datastore"):
            m._private_internal_url(url, kind=kind)


def test_preserves_authoritative_rediss_tls_for_render_key_value(m):
    """A secure Render URL cannot be normalized to a plaintext Redis URL."""
    secure = "rediss://red-secure-private:6379"
    assert m._private_internal_url(secure, kind="redis") == secure
    assert m._private_internal_url(
        "redis://red-secure-private:6379", kind="redis"
    ) == "redis://red-secure-private:6379"


def test_inspection_never_downgrades_or_accepts_wrong_redis_scheme(m):
    secure = "rediss://red-private:6379"

    class SecureKeyValue(FakeClient):
        def _request_path(self, endpoint, *, method):
            if endpoint == f"/v1/key-value/{KV}/connection-info":
                self.calls.append((method, endpoint))
                assert method == "GET"
                return {"internalConnectionString": secure}
            return super()._request_path(endpoint, method=method)

    env = safe_env(m)
    env["REDIS_URL"] = secure
    verified = inspect(m, SecureKeyValue(env))
    assert verified.ready
    assert "mismatch:REDIS_URL" not in verified.failures

    env["REDIS_URL"] = "redis://red-private:6379"
    rejected = inspect(m, SecureKeyValue(env))
    assert not rejected.ready
    assert "mismatch:REDIS_URL" in rejected.failures
    assert "red-private" not in repr(rejected)


def test_source_workflow_is_protected_and_read_only():
    text = (ROOT / ".github/workflows/render-beta-service-reconcile.yml").read_text()
    assert "inspect-env" in text
    assert "inspect-consumer" in text
    assert "--require-governed-history" in text
    assert "environment: beta-release" in text
    assert "RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}" in text
    assert "RENDER_BETA_POSTGRES_ID: ${{ vars.RENDER_BETA_POSTGRES_ID }}" in text
    assert "RENDER_BETA_KEY_VALUE_ID: ${{ vars.RENDER_BETA_KEY_VALUE_ID }}" in text
    assert "if: env.MODE == 'inspect-env'" in text
    assert "inspect_render_beta_environment.py" in text
    for dangerous in ("create_web_service", "create_postgres", "create_key_value"):
        assert dangerous not in text
