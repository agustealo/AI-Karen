"""Fail-closed provenance and loopback proof for disposable KCARD-01L runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPError, HTTPRedirectHandler, ProxyHandler, Request

SHA = {"a": None}


class GuardError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def loopback_origin(raw: str) -> str:
    parsed = urlsplit(raw)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port not in {8010, None}):
        raise GuardError("Card Studio local acceptance requires loopback http://127.0.0.1:8010")
    return parsed.scheme + "://" + parsed.netloc


def docker_json(args: list[str]) -> list[dict]:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise GuardError("Docker provenance inspection failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GuardError("Docker returned malformed provenance JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise GuardError("Docker provenance did not contain inspected objects")
    return value


def http_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-store"})
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=30) as response:
            if response.status != 200:
                raise GuardError("Required local endpoint returned non-200")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json":
                raise GuardError("Required local endpoint was not JSON")
            payload = json.load(response)
    except (HTTPError, OSError, TimeoutError) as exc:
        raise GuardError("Required local endpoint unavailable") from exc
    if not isinstance(payload, dict):
        raise GuardError("Required local endpoint returned invalid JSON")
    return payload


def local_storage_origin(raw: str) -> str:
    """Only the explicitly configured local Docker host gateway may serve fixture bytes."""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        valid = (
            parsed.scheme == "http" and parsed.hostname == "host.docker.internal"
            and port is not None and 1 <= port <= 65535
            and raw == f"http://host.docker.internal:{port}"
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise GuardError("Local Content Intelligence requires a canonical Docker-host Storage origin")
    return raw


def verify_local_storage_gateway(database_container: str, origin: str) -> dict:
    """Bind the configured Storage endpoint to the running local Supabase project."""
    port = str(urlsplit(local_storage_origin(origin)).port)
    databases = docker_json(["docker", "inspect", database_container])
    if len(databases) != 1:
        raise GuardError("Local Storage database identity is ambiguous")
    database = databases[0]
    name = database.get("Name")
    if (not isinstance(name, str) or not name.startswith("/supabase_db_")
            or database.get("State", {}).get("Running") is not True):
        raise GuardError("Local Storage database identity is invalid")
    gateway_name = "supabase_kong_" + name.removeprefix("/supabase_db_")
    gateways = docker_json(["docker", "inspect", gateway_name])
    if len(gateways) != 1:
        raise GuardError("Local Storage gateway is ambiguous")
    gateway = gateways[0]
    bindings = gateway.get("NetworkSettings", {}).get("Ports", {}).get("8000/tcp")
    gateway_id = gateway.get("Id")
    if (
        gateway.get("Name") != "/" + gateway_name
        or gateway.get("State", {}).get("Running") is not True
        or not isinstance(bindings, list) or not bindings
        or any(not isinstance(binding, dict) or binding.get("HostPort") != port
               for binding in bindings)
        or not isinstance(gateway_id, str) or len(gateway_id) != 64
        or any(ch not in "0123456789abcdef" for ch in gateway_id)
    ):
        raise GuardError("Configured local Storage gateway does not match the running project")
    return {"authority": "local_supabase_gateway", "container_id": gateway_id, "port": port}


def verify_explorer_runtime(
    service: str, container: dict, env: list[str], project: str, database: str,
    *, require_local_storage: bool = False,
) -> str | None:
    """Bind browser ingress and actual API DSNs to the dedicated local stack."""
    if not all(isinstance(item, str) and "=" in item for item in env):
        raise GuardError("Invalid runtime environment")
    values = dict(item.split("=", 1) for item in env)
    if len(values) != len(env):
        raise GuardError("Ambiguous runtime environment")
    labels = container.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != service
    ):
        raise GuardError("Container does not belong to the approved Compose service")
    if service == "web":
        ports = container.get("NetworkSettings", {}).get("Ports", {})
        if (
            values.get("KAREN_BACKEND_URL") != "http://api:8000"
            or ports.get("8010/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "8010"}]
        ):
            raise GuardError("Web ingress is not bound to the approved loopback stack")
        return
    required = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "production",
        "AUTH_DEV_MODE": "false",
        "AUTH_ALLOW_DEV_LOGIN": "false",
        "KARI_AUTH_BYPASS": "false",
        "AUTH_ENABLE_SESSION_VALIDATION": "true",
        "DB_HOST": "host.docker.internal",
        "DB_PORT": "54322",
        "DB_NAME": database,
    }
    if any(values.get(key) != value for key, value in required.items()):
        raise GuardError("API disposable database or security configuration differs")
    for key in ("DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL"):
        try:
            parsed = urlsplit(values.get(key, ""))
            valid = (
                parsed.scheme in {"postgresql", "postgresql+asyncpg"}
                and parsed.hostname == "host.docker.internal"
                and parsed.port == 54322
                and parsed.path == "/" + database
                and not parsed.query and not parsed.fragment
                and bool(parsed.username) and bool(parsed.password)
            )
        except ValueError:
            valid = False
        if not valid:
            raise GuardError("API connection URL does not target the disposable database")
    if require_local_storage:
        origin = local_storage_origin(values.get("SUPABASE_PROJECT_URL", ""))
        if values.get("SUPABASE_URL") not in (None, "", origin):
            raise GuardError("Conflicting local Storage origins")
        if not values.get("SUPABASE_SECRET_KEY", "").strip():
            raise GuardError("Local Storage credential is unavailable")
        return origin
    return None


def inspect_container(
    project: str, sha: str, service: str, *, explorer_database: str | None = None,
    env_path: Path | None = None, require_local_storage: bool = False,
) -> dict:
    compose = ["docker", "compose", "-p", project]
    if explorer_database is not None:
        compose.extend([
            "--env-file", str(env_path), "-f", "docker-compose.yml",
            "-f", "deploy/compose/docker-compose.prod.yml",
            "-f", "deploy/compose/docker-compose.local-card-studio.yml",
        ])
    ps = subprocess.run(
        [*compose, "ps", "-q", service],
        check=False, capture_output=True, text=True, timeout=30,
    )
    ids = [line.strip() for line in ps.stdout.splitlines() if line.strip()]
    if ps.returncode != 0 or len(ids) != 1:
        raise GuardError(f"Expected exactly one running {service} container")
    objects = docker_json(["docker", "inspect", ids[0]])
    container = objects[0]
    state = container.get("State")
    config = container.get("Config")
    if not isinstance(state, dict) or not isinstance(config, dict):
        raise GuardError(f"Incomplete {service} runtime metadata")
    if state.get("Running") is not True:
        raise GuardError(f"{service} container is not running")
    labels = config.get("Labels")
    env = config.get("Env")
    if not isinstance(labels, dict) or not isinstance(env, list):
        raise GuardError(f"Missing {service} provenance metadata")
    if labels.get("org.opencontainers.image.revision") != sha:
        raise GuardError(f"{service} container revision differs")
    revisions = [item.split("=", 1)[1] for item in env if item.startswith("KAREN_DEPLOYED_COMMIT_SHA=")]
    if revisions != [sha]:
        raise GuardError(f"{service} runtime SHA differs")
    if service == "api":
        required = {
            "KARI_ENABLE_CARD_STUDIO_CRUD=true",
            "AUTH_ALLOW_DEV_LOGIN=false",
            "KARI_AUTH_BYPASS=false",
            "AUTH_ENABLE_SESSION_VALIDATION=true",
        }
        if not required.issubset(set(env)):
            raise GuardError("API disposable security flags are incomplete")
    storage_origin = None
    if explorer_database is not None:
        storage_origin = verify_explorer_runtime(
            service, container, env, project, explorer_database,
            require_local_storage=require_local_storage,
        )
    image_id = container.get("Image")
    if not isinstance(image_id, str):
        raise GuardError(f"Missing {service} image identity")
    images = docker_json(["docker", "image", "inspect", image_id])
    image_config = images[0].get("Config")
    if not isinstance(image_config, dict):
        raise GuardError(f"Missing {service} image metadata")
    image_labels = image_config.get("Labels")
    if not isinstance(image_labels, dict) or image_labels.get("org.opencontainers.image.revision") != sha:
        raise GuardError(f"Built {service} image revision differs")
    if images[0].get("Id") != image_id:
        raise GuardError(f"Built {service} image ID differs")
    evidence = {"service": service, "container_id": ids[0], "image_id": image_id}
    if storage_origin is not None:
        evidence["storage_origin"] = storage_origin
    return evidence


def verify_local_supabase_database(env_path: Path, expected_database: str | None = None) -> dict:
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    db_name = values.get("KCARD_DB_NAME", "")
    if not db_name or not db_name.startswith("kcard_"):
        raise GuardError("Disposable local Supabase database name is missing")
    if expected_database is not None and db_name != expected_database:
        raise GuardError("Disposable database does not match the reviewed revision")
    containers = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if containers.returncode != 0:
        raise GuardError("Docker is unavailable for Supabase database verification")
    matches = [line.split("\t", 1)[0] for line in containers.stdout.splitlines()
               if "54322->5432/tcp" in line and line.startswith("supabase_db_")]
    if len(matches) != 1:
        raise GuardError("Canonical loopback local Supabase PostgreSQL is absent or ambiguous")
    target = matches[0]
    evidence = {"authority": "local_supabase", "database": db_name, "port": 54322, "status": "ready"}
    query = "SELECT current_database()"
    if expected_database is not None:
        inspected = docker_json(["docker", "inspect", target])
        if (
            len(inspected) != 1
            or inspected[0].get("Name") != "/" + target
            or inspected[0].get("State", {}).get("Running") is not True
        ):
            raise GuardError("Local PostgreSQL container identity is unavailable")
        container_id = inspected[0].get("Id")
        if (
            not isinstance(container_id, str) or len(container_id) != 64
            or any(ch not in "0123456789abcdef" for ch in container_id)
        ):
            raise GuardError("Local PostgreSQL container ID is invalid")
        target = container_id
        evidence["container_id"] = container_id
        query = "SELECT current_database(), oid FROM pg_database WHERE datname = current_database()"
    result = subprocess.run(
        ["docker", "exec", target, "psql", "-U", "postgres", "-d", db_name,
         "-tAc", query],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise GuardError("Disposable database is unavailable in local Supabase")
    output = result.stdout.strip()
    if expected_database is not None:
        name, separator, oid = output.partition("|")
        if name != db_name or separator != "|" or not oid.isascii() or not oid.isdecimal():
            raise GuardError("Disposable database identity could not be verified")
        evidence["database_oid"] = oid
    elif output != db_name:
        raise GuardError("Disposable database is unavailable in local Supabase")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--evidence", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--file-explorer", action="store_true")
    mode.add_argument("--content-intelligence", action="store_true")
    args = parser.parse_args()
    artifact_local = args.file_explorer or args.content_intelligence

    try:
        if len(args.sha) != 40 or any(ch not in "0123456789abcdef" for ch in args.sha):
            raise GuardError("Incorrect source SHA")
        origin = loopback_origin(args.base_url)
        env_path = Path(args.env_file)
        if not env_path.is_file() or env_path.stat().st_mode & 0o077:
            raise GuardError("Acceptance env file is missing or exposed")

        database = None
        if artifact_local:
            if origin != "http://127.0.0.1:8010" or args.project != "kcard-" + args.sha[:12]:
                raise GuardError("Explorer requires the dedicated exact-revision local stack")
            if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
                raise GuardError("Explicit Docker endpoint overrides are forbidden")
            contexts = docker_json(["docker", "context", "inspect"])
            if len(contexts) != 1 or not str(
                contexts[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
            ).startswith("unix://"):
                raise GuardError("Explorer requires a local Docker daemon")
            database = "kcard_" + args.sha[:12]
        api = inspect_container(
            args.project, args.sha, "api", explorer_database=database, env_path=env_path,
            require_local_storage=args.content_intelligence,
        )
        web = inspect_container(
            args.project, args.sha, "web", explorer_database=database, env_path=env_path
        )
        revision = http_json(origin + "/api/deployment-revision")
        if revision != {"status": "ok", "revision": args.sha}:
            raise GuardError("Running deployment revision differs from reviewed SHA")
        health = http_json(origin + "/api/health")
        if health.get("status") != "ok" or health.get("backend_ready") is not True:
            raise GuardError("Canonical backend is not ready")
        supabase_database = verify_local_supabase_database(env_path, database)

        evidence = {
            "decision": "PASS",
            "scenario": ("content-intelligence" if args.content_intelligence
                         else "file-explorer" if args.file_explorer else "card-studio"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_sha": args.sha,
            "project": args.project,
            "origin": origin,
            "containers": {"api": api, "web": web},
            "supabase_database": supabase_database,
        }
        if args.content_intelligence:
            evidence["supabase_storage"] = verify_local_storage_gateway(
                supabase_database["container_id"], api["storage_origin"],
            )
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        evidence_path.chmod(0o600)
        print("LOCAL_CONTENT_INTELLIGENCE_PROVENANCE_PASS" if args.content_intelligence
              else "LOCAL_FILE_EXPLORER_PROVENANCE_PASS" if args.file_explorer
              else "LOCAL_CARD_STUDIO_PROVENANCE_PASS")
        return 0
    except GuardError as exc:
        prefix = "LOCAL_CONTENT_INTELLIGENCE_PROVENANCE_FAIL" if args.content_intelligence else "LOCAL_FILE_EXPLORER_PROVENANCE_FAIL" if args.file_explorer else "LOCAL_CARD_STUDIO_PROVENANCE_FAIL"
        print(f"{prefix}: {exc}")
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("LOCAL_CONTENT_INTELLIGENCE_PROVENANCE_FAIL" if args.content_intelligence else "LOCAL_FILE_EXPLORER_PROVENANCE_FAIL" if args.file_explorer else "LOCAL_CARD_STUDIO_PROVENANCE_FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
