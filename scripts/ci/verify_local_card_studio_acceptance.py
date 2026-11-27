"""Fail-closed provenance and loopback proof for disposable KCARD-01L runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import os
import subprocess
import tomllib
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


def local_supabase_database_config(path: Path | None = None) -> tuple[str, int]:
    """Read the existing local Supabase project identity and database port."""
    config_path = path or Path(__file__).resolve().parents[2] / "supabase/config.toml"
    try:
        with config_path.open("rb") as stream:
            config = tomllib.load(stream)
        project = config["project_id"]
        port = config["db"]["port"]
    except (OSError, ValueError, KeyError, TypeError):
        raise GuardError("Canonical local Supabase configuration is unavailable") from None
    if (
        not isinstance(project, str) or not 1 <= len(project) <= 64
        or not project[0].isascii() or not project[0].isalnum()
        or any(not ch.isascii() or not (ch.isalnum() or ch in "_-") for ch in project)
        or type(port) is not int or not 1 <= port <= 65535
    ):
        raise GuardError("Canonical local Supabase configuration is invalid")
    return project, port


def local_supabase_database_container(project: str, port: int) -> str:
    """Verify the configured project's actual running PostgreSQL container."""
    name = "supabase_db_" + project
    objects = docker_json(["docker", "inspect", name])
    if len(objects) != 1:
        raise GuardError("Canonical local Supabase database is absent or ambiguous")
    container = objects[0]
    identity = container.get("Id")
    bindings = container.get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp")
    if (
        container.get("Name") != "/" + name
        or container.get("State", {}).get("Running") is not True
        or not isinstance(identity, str) or len(identity) != 64
        or any(ch not in "0123456789abcdef" for ch in identity)
        or not isinstance(bindings, list) or not bindings
        or any(not isinstance(binding, dict) or binding.get("HostPort") != str(port)
               for binding in bindings)
    ):
        raise GuardError("Local Supabase database does not match the configured identity")
    return identity


def require_local_docker() -> None:
    """Reject remote Docker endpoint overrides before inspecting fixture services."""
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise GuardError("Explicit Docker endpoint overrides are forbidden")
    contexts = docker_json(["docker", "context", "inspect"])
    if len(contexts) != 1 or not str(
        contexts[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
    ).startswith("unix://"):
        raise GuardError("Acceptance requires a local Docker daemon")


def local_storage_origin(raw: str, *, host_loopback: bool = False, require_https: bool = False) -> str:
    """Require an exact local origin for the intended execution environment."""
    host = "127.0.0.1" if host_loopback else "host.docker.internal"
    scheme = "https" if require_https else "http"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        valid = (
            parsed.scheme == scheme and parsed.hostname == host
            and port is not None and 1 <= port <= 65535
            and raw == f"{scheme}://{host}:{port}"
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise GuardError("Local acceptance requires a canonical local Storage origin")
    return raw


def verify_local_storage_gateway(
    database_container: str, origin: str, *, host_loopback: bool = False,
) -> dict:
    """Bind the configured Storage endpoint to the running local Supabase project."""
    tls = origin.startswith("https://") and not host_loopback
    port = str(urlsplit(local_storage_origin(
        origin, host_loopback=host_loopback, require_https=tls,
    )).port)
    if tls:
        try:
            with (Path(__file__).resolve().parents[2] / "supabase/config.toml").open("rb") as stream:
                configured = tomllib.load(stream)["api"]["port"]
        except (OSError, ValueError, KeyError, TypeError):
            raise GuardError("Canonical local API port unavailable") from None
        if type(configured) is not int or str(configured) != port:
            raise GuardError("Local TLS gateway port differs from canonical configuration")
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
    bindings = gateway.get("NetworkSettings", {}).get("Ports", {}).get("8443/tcp" if tls else "8000/tcp")
    gateway_id = gateway.get("Id")
    if (
        gateway.get("Name") != "/" + gateway_name
        or gateway.get("State", {}).get("Running") is not True
        or not isinstance(bindings, list) or not bindings
        or any(not isinstance(binding, dict) or binding.get("HostPort") != port
               or (host_loopback and binding.get("HostIp") != "127.0.0.1")
               for binding in bindings)
        or not isinstance(gateway_id, str) or len(gateway_id) != 64
        or any(ch not in "0123456789abcdef" for ch in gateway_id)
    ):
        raise GuardError("Configured local Storage gateway does not match the running project")
    evidence = {"authority": "local_supabase_gateway", "container_id": gateway_id, "port": port}
    if tls:
        evidence["transport"] = "https"
    return evidence


STORAGE_CA_MOUNT = "/run/karen-local-storage-tls"
STORAGE_CA_FILE = STORAGE_CA_MOUNT + "/ca.pem"


def validate_storage_ca(path: Path) -> bytes:
    """Read and validate the exact public CA bundle before copying it."""
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError
        with path.open("rb") as stream:
            data = stream.read(256 * 1024 + 1)
        if not data or len(data) > 256 * 1024 or b"PRIVATE KEY" in data:
            raise ValueError
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=data.decode("ascii"))
    except (OSError, ValueError, UnicodeError):
        raise GuardError("Invalid local Storage CA bundle") from None
    return data


def verify_storage_tls_runtime(container: dict, container_id: str, env_path: Path, origin: str) -> dict:
    """Prove CA mount identity and a verified TLS handshake from the API namespace."""
    directory = env_path.resolve().parent / "storage-tls"
    ca = validate_storage_ca(directory / "ca.pem")
    mounts = container.get("Mounts", [])
    if not isinstance(mounts, list):
        raise GuardError("Local Storage CA mount is unavailable")
    matches = [mount for mount in mounts if isinstance(mount, dict)
               and mount.get("Destination") == STORAGE_CA_MOUNT]
    if (len(matches) != 1 or matches[0].get("Type") != "bind"
            or matches[0].get("RW") is not False
            or matches[0].get("Source") != str(directory)):
        raise GuardError("Local Storage CA mount identity differs")
    probe = """import hashlib, json, os, socket
from pathlib import Path
from urllib.parse import urlsplit
from ai_karen_engine.config.artifact_storage import StorageTLSPolicy
origin = os.environ["SUPABASE_PROJECT_URL"]
policy = StorageTLSPolicy.from_environment(origin)
if policy is None:
    raise RuntimeError("TLS policy unavailable")
parts = urlsplit(origin)
with socket.create_connection((parts.hostname, parts.port), timeout=5) as raw:
    with policy.verify_for_origin(origin).wrap_socket(raw, server_hostname=parts.hostname) as conn:
        peer = conn.getpeercert(binary_form=True)
print(json.dumps({"origin": origin, "ca_sha256": hashlib.sha256(
    Path(os.environ["KAREN_SUPABASE_STORAGE_TLS_CA_FILE"]).read_bytes()).hexdigest(),
    "peer_sha256": hashlib.sha256(peer).hexdigest()}))
"""
    result = subprocess.run(
        ["docker", "exec", container_id, "python", "-c", probe],
        check=False, capture_output=True, text=True, timeout=30,
    )
    try:
        evidence = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise GuardError("Local Storage TLS handshake unavailable") from None
    peer = evidence.get("peer_sha256") if isinstance(evidence, dict) else None
    if (result.returncode != 0 or not isinstance(evidence, dict)
            or set(evidence) != {"origin", "ca_sha256", "peer_sha256"}
            or evidence["origin"] != origin
            or evidence["ca_sha256"] != hashlib.sha256(ca).hexdigest()
            or not isinstance(peer, str) or len(peer) != 64
            or any(ch not in "0123456789abcdef" for ch in peer)):
        raise GuardError("Local Storage TLS identity could not be verified")
    return evidence


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
    _, database_port = local_supabase_database_config()
    required = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "production",
        "AUTH_DEV_MODE": "false",
        "AUTH_ALLOW_DEV_LOGIN": "false",
        "KARI_AUTH_BYPASS": "false",
        "AUTH_ENABLE_SESSION_VALIDATION": "true",
        "DB_HOST": "host.docker.internal",
        "DB_PORT": str(database_port),
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
                and parsed.port == database_port
                and parsed.path == "/" + database
                and not parsed.query and not parsed.fragment
                and bool(parsed.username) and bool(parsed.password)
            )
        except ValueError:
            valid = False
        if not valid:
            raise GuardError("API connection URL does not target the disposable database")
    if require_local_storage:
        origin = local_storage_origin(values.get("SUPABASE_PROJECT_URL", ""), require_https=True)
        if (values.get("KAREN_SUPABASE_STORAGE_TLS_ORIGIN") != origin
                or values.get("KAREN_SUPABASE_STORAGE_TLS_CA_FILE") != STORAGE_CA_FILE):
            raise GuardError("Local Storage TLS policy differs from the approved origin or CA")
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
        if env_path is None:
            raise GuardError("Private local Storage environment is missing")
        evidence["storage_tls"] = verify_storage_tls_runtime(container, ids[0], env_path, storage_origin)
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
    project, port = local_supabase_database_config()
    if values.get("KCARD_DB_PORT") != str(port):
        raise GuardError("Disposable database port differs from canonical local configuration")
    target = local_supabase_database_container(project, port)
    evidence = {"authority": "local_supabase", "database": db_name, "port": port, "status": "ready"}
    query = "SELECT current_database()"
    if expected_database is not None:
        evidence["container_id"] = target
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
    mode.add_argument("--owner-text", action="store_true")
    args = parser.parse_args()
    artifact_local = args.file_explorer or args.content_intelligence or args.owner_text
    require_local_storage = args.content_intelligence or args.owner_text
    scenario, prefix = (
        ("file-explorer-owner-text", "LOCAL_FILE_EXPLORER_OWNER_TEXT_PROVENANCE")
        if args.owner_text else
        ("content-intelligence", "LOCAL_CONTENT_INTELLIGENCE_PROVENANCE")
        if args.content_intelligence else
        ("file-explorer", "LOCAL_FILE_EXPLORER_PROVENANCE")
        if args.file_explorer else
        ("card-studio", "LOCAL_CARD_STUDIO_PROVENANCE")
    )

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
            require_local_docker()
            database = "kcard_" + args.sha[:12]
        api = inspect_container(
            args.project, args.sha, "api", explorer_database=database, env_path=env_path,
            require_local_storage=require_local_storage,
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
            "scenario": scenario,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_sha": args.sha,
            "project": args.project,
            "origin": origin,
            "containers": {"api": api, "web": web},
            "supabase_database": supabase_database,
        }
        if require_local_storage:
            evidence["supabase_storage"] = verify_local_storage_gateway(
                supabase_database["container_id"], api["storage_origin"],
            )
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        evidence_path.chmod(0o600)
        print(f"{prefix}_PASS")
        return 0
    except GuardError as exc:
        print(f"{prefix}_FAIL: {exc}")
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(f"{prefix}_FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
