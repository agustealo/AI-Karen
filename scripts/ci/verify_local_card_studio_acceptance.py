"""Fail-closed provenance and loopback proof for disposable KCARD-01L runs."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPError, HTTPRedirectHandler, Request

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
        with build_opener(NoRedirects()).open(request, timeout=30) as response:
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


def inspect_container(project: str, sha: str, service: str) -> dict:
    ps = subprocess.run(
        ["docker", "compose", "-p", project, "ps", "-q", service],
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
    return {"service": service, "container_id": ids[0][:12], "image_id": image_id}


def verify_local_supabase_database(env_path: Path) -> dict:
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    db_name = values.get("KCARD_DB_NAME", "")
    if not db_name or not db_name.startswith("kcard_"):
        raise GuardError("Disposable local Supabase database name is missing")
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
    result = subprocess.run(
        ["docker", "exec", matches[0], "psql", "-U", "postgres", "-d", db_name,
         "-tAc", "SELECT current_database()"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0 or result.stdout.strip() != db_name:
        raise GuardError("Disposable database is unavailable in local Supabase")
    return {"authority": "local_supabase", "database": db_name, "port": 54322, "status": "ready"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    try:
        if len(args.sha) != 40 or any(ch not in "0123456789abcdef" for ch in args.sha):
            raise GuardError("Incorrect source SHA")
        origin = loopback_origin(args.base_url)
        env_path = Path(args.env_file)
        if not env_path.is_file() or env_path.stat().st_mode & 0o077:
            raise GuardError("Acceptance env file is missing or exposed")

        api = inspect_container(args.project, args.sha, "api")
        web = inspect_container(args.project, args.sha, "web")
        revision = http_json(origin + "/api/deployment-revision")
        if revision != {"status": "ok", "revision": args.sha}:
            raise GuardError("Running deployment revision differs from reviewed SHA")
        health = http_json(origin + "/api/health")
        if health.get("status") != "ok" or health.get("backend_ready") is not True:
            raise GuardError("Canonical backend is not ready")
        supabase_database = verify_local_supabase_database(env_path)

        evidence = {
            "decision": "PASS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_sha": args.sha,
            "project": args.project,
            "origin": origin,
            "containers": {"api": api, "web": web},
            "supabase_database": supabase_database,
        }
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        evidence_path.chmod(0o600)
        print("LOCAL_CARD_STUDIO_PROVENANCE_PASS")
        return 0
    except GuardError as exc:
        print(f"LOCAL_CARD_STUDIO_PROVENANCE_FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
