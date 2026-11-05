"""Audit the existing Render beta API's environment without exposing secrets.

Read-only. Canonical production-required names are parsed from server/config.py;
desired service identity, runtime and datastore names come from the Blueprint.
It does not create services, modify variables, start deploys or open public DB access.
"""
from __future__ import annotations

import argparse
import ast
import base64
import binascii
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from reconcile_render_beta_service import (
    Manifest,
    ReconcileError,
    RenderClient,
    SERVICE_ID_PATTERN,
    WORKSPACE_ID_PATTERN,
    verify_identity,
)

ROOT = Path(__file__).resolve().parents[2]
SERVER_CONFIG = ROOT / "src/ai_karen_engine/server/config.py"
BLUEPRINT = ROOT / "deploy/render/render.yaml"

PROTECTED_SECRETS = frozenset({
    "KARI_DUCKDB_PASSWORD",
    "KARI_JOB_ENC_KEY",
    "KARI_JOB_SIGNING_KEY",
    "KARI_MODEL_SIGNING_KEY",
    "SECRET_KEY",
    "AUTH_SECRET_KEY",
    "AUTH_JWT_SECRET_KEY",
    "EXTENSION_SECRET_KEY",
    "EXTENSION_API_KEY",
})
SAFE_FLAGS = frozenset({
    "AUTH_DEV_MODE",
    "AUTH_ALLOW_DEV_LOGIN",
    "KARI_AUTH_BYPASS",
    "KARI_FAST_STARTUP",
    "KARI_SKIP_STARTUP_CHECK",
    "KARI_SKIP_AUTO_INIT",
    "KARI_DEFER_ROUTER_WIRING",
    "EXTENSION_DEV_BYPASS_ENABLED",
})
ADDITIONAL_REQUIRED = frozenset({"AUTH_JWT_SECRET_KEY", "KARI_CORS_ORIGINS"})
GOVERNED_HISTORY_REQUIRED = frozenset({
    "KARI_ENABLE_AG_UI_BRIDGE",
    "KARI_ENABLE_AG_UI_DURABLE_RUNS",
})
AG_UI_EVENT_JOURNAL = "KARI_ENABLE_AG_UI_EVENT_JOURNAL"
MAX_REPORT_ITEMS = 100


@dataclass(frozen=True, slots=True)
class Report:
    failures: tuple[str, ...]
    advisories: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.failures


def required_environment_defaults(path: Path) -> dict[str, str]:
    """Read the canonical declared names/defaults without importing production config."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "required_env_vars"
            for target in node.targets
        ):
            if not isinstance(node.value, ast.Dict):
                break
            try:
                defaults = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                break
            if (isinstance(defaults, dict) and defaults
                    and all(isinstance(k, str) and isinstance(v, str)
                            for k, v in defaults.items())):
                return defaults
    raise ReconcileError("Canonical required environment contract cannot be inspected")


def reference_name(blueprint: str, *, key: str, ref_kind: str) -> str:
    if ref_kind not in {"fromDatabase", "fromService"}:
        raise ReconcileError("Unsupported Blueprint resource reference")
    matches = re.findall(
        rf"^      - key: {re.escape(key)}\s*\n"
        rf"        {ref_kind}:\s*\n"
        r"          name: ([A-Za-z0-9][A-Za-z0-9-]+)\s*$",
        blueprint,
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise ReconcileError(f"Reviewed Blueprint has no unique {key} resource reference")
    return matches[0]


def _private_internal_url(raw: Any, *, kind: str) -> str:
    if not isinstance(raw, str) or not raw or any(ord(c) <= 32 for c in raw):
        raise ReconcileError("Existing Render private connection URL is unavailable")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname or ""
        # Normalize only the Postgres driver alias. Render Key Value may
        # supply rediss://; never turn an authenticated TLS URL into redis://.
        scheme = "postgresql" if kind == "postgres" else parsed.scheme
        schemes = {"postgresql", "postgres"} if kind == "postgres" else {"redis", "rediss"}
        prefix = "dpg-" if kind == "postgres" else "red-"
        if (parsed.scheme not in schemes or not hostname.startswith(prefix)
                or "." in hostname or not parsed.path.startswith("/") and kind == "postgres"
                or parsed.fragment or parsed.query and kind == "redis"):
            raise ReconcileError("Existing Render connection info is not a private datastore URL")
        if not parsed.netloc or parsed.port not in {None, 5432 if kind == "postgres" else 6379}:
            raise ReconcileError("Existing Render connection info has unexpected port or host")
        if kind == "postgres" and not parsed.username:
            raise ReconcileError("Existing Render database identity is incomplete")
        return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        raise ReconcileError("Existing Render connection info is malformed") from None


def _env_records(items: list) -> dict[str, str]:
    values: dict[str, str] = {}
    for entry in items:
        item = entry.get("envVar") if isinstance(entry, dict) else None
        if not isinstance(item, dict):
            raise ReconcileError("Existing Render environment inventory has invalid structure")
        name, value = item.get("key"), item.get("value")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", name)
                or name in values or not isinstance(value, str)):
            raise ReconcileError("Existing Render environment inventory is ambiguous")
        values[name] = value
    return values


def _fernet_material_valid(value: str) -> bool:
    try:
        return len(base64.b64decode(value, altchars=b"-_", validate=True)) == 32
    except (ValueError, binascii.Error):
        return False


def _origins_secure(value: str) -> bool:
    if not value:
        return False
    for origin in value.split(","):
        origin = origin.strip()
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if (parsed.scheme != "https" or not parsed.hostname
                or "." not in parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or "*" in origin or parsed.hostname.endswith((".local", ".internal"))):
            return False
    return True


def _verify_resource(resource: dict, *, resource_id: str, owner_id: str, name: str, region: str) -> None:
    owner = resource.get("owner")
    if (resource.get("id") != resource_id
            or not isinstance(owner, dict) or owner.get("id") != owner_id
            or resource.get("name") != name or resource.get("region") != region
            or resource.get("status") != "available"):
        raise ReconcileError("Existing Render datastore identity, region or availability mismatch")


def _linked_group_present(groups: list, *, service_id: str, workspace_id: str) -> bool:
    for group in groups:
        if not isinstance(group, dict):
            raise ReconcileError("Render environment group inventory has invalid structure")
        if group.get("ownerId") != workspace_id:
            raise ReconcileError("Render environment group owner mismatch")
        links = group.get("serviceLinks")
        if not isinstance(links, list):
            raise ReconcileError("Render environment group service links missing")
        if any(isinstance(link, dict) and link.get("id") == service_id for link in links):
            return True
    return False


def inspect(
    *,
    client: RenderClient,
    service_id: str,
    workspace_id: str,
    postgres_id: str,
    key_value_id: str,
    manifest: Manifest,
    blueprint: str,
    required_defaults: dict[str, str],
    require_governed_history: bool = False,
) -> Report:
    if (not SERVICE_ID_PATTERN.fullmatch(service_id)
            or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id)
            or not re.fullmatch(r"dpg-[a-z0-9-]+", postgres_id)
            or not re.fullmatch(r"red-[a-z0-9-]+", key_value_id)):
        raise ReconcileError("Invalid existing Render resource IDs")

    service = client.get(service_id)
    verify_identity(service, service_id=service_id, workspace_id=workspace_id, manifest=manifest)
    details = service.get("serviceDetails")
    if not isinstance(details, dict) or not isinstance(details.get("region"), str):
        raise ReconcileError("Existing Render service runtime metadata is incomplete")
    region = details["region"]
    pg = client.inspect_resource("postgres", postgres_id)
    kv = client.inspect_resource("key-value", key_value_id)
    _verify_resource(pg, resource_id=postgres_id, owner_id=workspace_id,
                     name=reference_name(blueprint, key="DATABASE_URL", ref_kind="fromDatabase"),
                     region=region)
    _verify_resource(kv, resource_id=key_value_id, owner_id=workspace_id,
                     name=reference_name(blueprint, key="REDIS_URL", ref_kind="fromService"),
                     region=region)

    # Environment group variables are invisible to the service-level list API.
    # A group's keys can collide with or override expectations. Do not infer.
    groups = client.inspect_env_groups(workspace_id)
    if _linked_group_present(groups, service_id=service_id, workspace_id=workspace_id):
        raise ReconcileError("Linked environment groups need private manual review")

    env = _env_records(client.inspect_env_vars(service_id))
    required_names = set(required_defaults) | ADDITIONAL_REQUIRED | SAFE_FLAGS | {
        "ENVIRONMENT", "AUTH_MODE", "EXTENSION_REQUIRE_HTTPS",
    }
    failures: set[str] = set()
    advisories: set[str] = set()
    for name in sorted(required_names):
        if not env.get(name):
            failures.add(f"missing:{name}")

    if service.get("branch") != manifest.branch:
        failures.add("drift:branch")
    if service.get("autoDeployTrigger") != "off" and service.get("autoDeploy") != "no":
        failures.add("drift:auto_deploy")
    if details.get("healthCheckPath") != manifest.health_check_path:
        failures.add("drift:health_check")

    for key in SAFE_FLAGS:
        if env.get(key) and env[key].lower() != "false":
            failures.add(f"insecure:{key}")
    for key, expected in {"ENVIRONMENT": "production", "AUTH_MODE": "production",
                          "EXTENSION_REQUIRE_HTTPS": "true"}.items():
        if env.get(key) and env[key].lower() != expected:
            failures.add(f"insecure:{key}")
    for key in PROTECTED_SECRETS:
        value = env.get(key, "")
        if value and (value == required_defaults.get(key) or len(value) < 32 or
                      "change-me" in value.lower() or "placeholder" in value.lower()):
            failures.add(f"insecure:{key}")
    if env.get("KARI_JOB_ENC_KEY") and not _fernet_material_valid(env["KARI_JOB_ENC_KEY"]):
        failures.add("invalid:KARI_JOB_ENC_KEY")
    if env.get("KARI_CORS_ORIGINS") and not _origins_secure(env["KARI_CORS_ORIGINS"]):
        failures.add("insecure:KARI_CORS_ORIGINS")

    # Initial application boot and consumer-history acceptance are different
    # gates. Never enable experimental AG-UI automatically: release operators
    # must first prove migration 43 and the durable-run storage contract.
    # This opt-in check only validates the configured feature switches.
    history_enabled = all(
        env.get(key, "").strip().lower() == "true"
        for key in GOVERNED_HISTORY_REQUIRED
    )
    if require_governed_history and not history_enabled:
        for key in GOVERNED_HISTORY_REQUIRED:
            if env.get(key, "").strip().lower() != "true":
                failures.add(f"disabled:{key}")
    if (env.get(AG_UI_EVENT_JOURNAL, "").strip().lower() == "true"
            and not history_enabled):
        failures.add(f"invalid:{AG_UI_EVENT_JOURNAL}")

    # A read-only Render API fetch receives the connection info as confidential
    # in-memory data, then checks only canonical internal URL equality.
    # Never emit raw credentials, hostnames or the upstream JSON.
    pg_info = client._request_path(f"/v1/postgres/{postgres_id}/connection-info", method="GET")
    kv_info = client._request_path(f"/v1/key-value/{key_value_id}/connection-info", method="GET")
    if not isinstance(pg_info, dict) or not isinstance(kv_info, dict):
        raise ReconcileError("Render datastore connection information is unavailable")
    expected_db = _private_internal_url(pg_info.get("internalConnectionString"), kind="postgres")
    expected_redis = _private_internal_url(kv_info.get("internalConnectionString"), kind="redis")
    expected_async = expected_db.replace("postgresql://", "postgresql+asyncpg://", 1)
    for key, expected in {
        "DATABASE_URL": expected_db,
        "POSTGRES_URL": expected_async,
        "AUTH_DATABASE_URL": expected_async,
        "REDIS_URL": expected_redis,
    }.items():
        if env.get(key) and env[key] != expected:
            failures.add(f"mismatch:{key}")

    if pg.get("plan") == "free":
        advisories.add("production_persistence:postgres_free_plan")
    if pg.get("expiresAt"):
        advisories.add("production_persistence:postgres_expiration_present")
    if details.get("plan") == "free":
        advisories.add("production_capacity:api_free_plan")
    if kv.get("plan") == "free":
        advisories.add("production_cache:key_value_free_plan")

    if len(failures) + len(advisories) > MAX_REPORT_ITEMS:
        raise ReconcileError("Render environment preflight report exceeded safety limits")
    return Report(tuple(sorted(failures)), tuple(sorted(advisories)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only existing Render beta environment preflight")
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--postgres-id", required=True)
    parser.add_argument("--key-value-id", required=True)
    parser.add_argument("--manifest", type=Path, default=BLUEPRINT)
    parser.add_argument(
        "--require-governed-history", action="store_true",
        help="Also require explicit AG-UI bridge and durable-run settings; "
             "does not attest migrations or browser behavior",
    )
    args = parser.parse_args(argv)
    try:
        from os import environ
        client = RenderClient(environ.get("RENDER_API_KEY", ""))
        blueprint = args.manifest.read_text(encoding="utf-8")
        report = inspect(
            client=client,
            service_id=args.service_id,
            workspace_id=args.workspace_id,
            postgres_id=args.postgres_id,
            key_value_id=args.key_value_id,
            manifest=Manifest.read(args.manifest),
            blueprint=blueprint,
            required_defaults=required_environment_defaults(SERVER_CONFIG),
            require_governed_history=args.require_governed_history,
        )
    except (ReconcileError, OSError, ValueError) as exc:
        if isinstance(exc, OSError):
            print("FAILED: Existing Render preflight source is unreadable", file=sys.stderr)
        elif isinstance(exc, ValueError) and not isinstance(exc, ReconcileError):
            print("FAILED: Invalid Render environment configuration", file=sys.stderr)
        else:
            print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print("Render beta environment audit (read-only, secrets excluded)")
    if args.require_governed_history:
        print("Governed-history switches checked; migrations and live browser proof remain separate")
    for line in report.failures:
        print(f"FAIL: {line}")
    for line in report.advisories:
        print(f"REVIEW: {line}")
    print("PASS: Existing Render runtime environment" if report.ready else
          "FAIL: Existing Render runtime environment not ready")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
