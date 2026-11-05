"""Reconcile an existing Render beta API's Git source and HTTP liveness path.

No service creation, environment mutation, production secret disclosure, or
implicit deployment. The checked-in Render Blueprint is the desired state.
The protected GitHub workflow verifies the exact reviewed main commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

API_ORIGIN = "https://api.render.com"
SERVICE_ID_PATTERN = re.compile(r"^srv-[a-z0-9]+$")
WORKSPACE_ID_PATTERN = re.compile(r"^tea-[a-z0-9]+$")
REPO_PATTERN = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_RESPONSE_BYTES = 65536


class ReconcileError(Exception):
    """An operator-safe failure; never carries API bodies or secrets."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class Manifest:
    name: str
    repo: str
    branch: str
    auto_deploy_trigger: str
    health_check_path: str

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        source = path.read_text(encoding="utf-8")
        if len(re.findall(r"^services:\s*$", source, re.MULTILINE)) != 1:
            raise ReconcileError("Blueprint must contain one services root")
        if len(re.findall(r"^  - type: web\s*$", source, re.MULTILINE)) != 1:
            raise ReconcileError("Blueprint must declare exactly one web service")

        def scalar(key: str) -> str:
            values = re.findall(rf"^    {re.escape(key)}: ([^#\r\n]+)$", source, re.MULTILINE)
            if len(values) != 1:
                raise ReconcileError(f"Blueprint must declare one {key} setting")
            return values[0].strip()

        manifest = cls(
            name=scalar("name"),
            repo=scalar("repo"),
            branch=scalar("branch"),
            auto_deploy_trigger=scalar("autoDeployTrigger"),
            health_check_path=scalar("healthCheckPath"),
        )
        if (
            manifest.branch != "main"
            or manifest.auto_deploy_trigger != "off"
            or manifest.health_check_path != "/health/live"
            or not REPO_PATTERN.fullmatch(manifest.repo)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", manifest.name)
        ):
            raise ReconcileError("Blueprint must use reviewed main, manual deploy, HTTP liveness and a canonical GitHub repo")
        return manifest


def _health_check_path(service: dict[str, Any]) -> str:
    """Read one web-service HTTP probe; an unset path is expected legacy drift."""
    details = service.get("serviceDetails")
    if not isinstance(details, dict):
        raise ReconcileError("Render web-service details cannot be verified")
    path = details.get("healthCheckPath", "")
    if not isinstance(path, str):
        raise ReconcileError("Render web-service health-check path is malformed")
    return path


def _trigger(service: dict[str, Any]) -> str:
    trigger = service.get("autoDeployTrigger")
    if trigger in {"off", "commit", "checksPass"}:
        return trigger
    # Render retains the legacy autoDeploy field on older services.
    legacy = service.get("autoDeploy")
    if legacy == "no":
        return "off"
    if legacy == "yes":
        return "commit"
    raise ReconcileError("Render service auto-deploy state cannot be verified")


class RenderClient:
    def __init__(self, token: str, *, opener: Any = None) -> None:
        if not token or any(ord(c) < 33 or ord(c) == 127 for c in token):
            raise ReconcileError("Render API credential is missing or malformed")
        self._token = token
        self._opener = opener if opener is not None else build_opener(NoRedirects())

    def _request_path(
        self, path: str, *, method: str, body: dict | None = None,
    ) -> Any:
        """Render's single bounded HTTP transport, including read-only inventory."""
        if (
            not path.startswith("/v1/")
            or ".." in path
            or any(ord(char) < 33 or ord(char) == 127 for char in path)
            or method not in {"GET", "PATCH"}
            or (method == "GET" and body is not None)
        ):
            raise ReconcileError("Unsafe Render API operation")
        url = f"{API_ORIGIN}{path}"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise ReconcileError(f"Render API returned unexpected HTTP {response.status}")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise ReconcileError(f"Render API rejected {method} with HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ReconcileError("Render API service connection failed") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ReconcileError("Render API response exceeds safe size limit")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ReconcileError("Render API response is not valid JSON") from None

    def _request(self, service_id: str, *, method: str, body: dict | None = None) -> dict:
        if not SERVICE_ID_PATTERN.fullmatch(service_id):
            raise ReconcileError("Render service ID is invalid")
        result = self._request_path(
            f"/v1/services/{service_id}", method=method, body=body,
        )
        if not isinstance(result, dict):
            raise ReconcileError("Render API service response has invalid shape")
        return result

    def inspect_resource(self, kind: str, resource_id: str) -> dict:
        """Read approved existing service datastore metadata, never a creation API."""
        allowed = {
            "postgres": r"dpg-[a-z0-9-]+",
            "key-value": r"red-[a-z0-9-]+",
        }
        if kind not in allowed or not re.fullmatch(allowed[kind], resource_id):
            raise ReconcileError("Invalid existing Render resource identity")
        result = self._request_path(f"/v1/{kind}/{resource_id}", method="GET")
        if not isinstance(result, dict):
            raise ReconcileError("Invalid Render resource metadata")
        return result

    def inspect_env_vars(self, service_id: str) -> list:
        if not SERVICE_ID_PATTERN.fullmatch(service_id):
            raise ReconcileError("Invalid existing Render service ID")
        # A full page might conceal additional keys. Rather than infer
        # completeness and potentially miss conflicting secrets, fail closed.
        result = self._request_path(
            f"/v1/services/{service_id}/env-vars?limit=100", method="GET",
        )
        if not isinstance(result, list) or len(result) >= 100:
            raise ReconcileError("Render service environment inventory is not complete")
        return result

    def inspect_env_groups(self, workspace_id: str) -> list:
        if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise ReconcileError("Invalid existing Render workspace ID")
        result = self._request_path(
            f"/v1/env-groups?ownerId={workspace_id}&limit=100", method="GET",
        )
        if not isinstance(result, list) or len(result) >= 100:
            raise ReconcileError("Render environment group inventory is not complete")
        return result

    def get(self, service_id: str) -> dict:
        return self._request(service_id, method="GET")

    def patch_source(self, service_id: str, manifest: Manifest) -> None:
        self._request(
            service_id,
            method="PATCH",
            body={
                "branch": manifest.branch,
                "autoDeployTrigger": manifest.auto_deploy_trigger,
                "serviceDetails": {"healthCheckPath": manifest.health_check_path},
            },
        )


def verify_identity(service: dict, *, service_id: str, workspace_id: str, manifest: Manifest) -> None:
    if (
        service.get("id") != service_id
        or service.get("ownerId") != workspace_id
        or service.get("name") != manifest.name
        or service.get("repo") != manifest.repo
        or service.get("type") != "web_service"
    ):
        raise ReconcileError("Render service ownership, source or type does not match the reviewed Blueprint")


def reconcile(
    *,
    client: RenderClient,
    service_id: str,
    workspace_id: str,
    manifest: Manifest,
    mode: str,
) -> str:
    if not SERVICE_ID_PATTERN.fullmatch(service_id):
        raise ReconcileError("Invalid existing Render service ID")
    if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise ReconcileError("Invalid existing Render workspace ID")
    if mode not in {"inspect", "apply"}:
        raise ReconcileError("Unknown reconciliation mode")
    current = client.get(service_id)
    verify_identity(current, service_id=service_id, workspace_id=workspace_id, manifest=manifest)
    # Validate the existing HTTP service shape before deciding on source drift.
    # A branch mismatch must never short-circuit a malformed health configuration.
    existing_health_path = _health_check_path(current)
    drift = (
        current.get("branch") != manifest.branch
        or _trigger(current) != manifest.auto_deploy_trigger
        or existing_health_path != manifest.health_check_path
    )
    if not drift:
        return "Existing Render beta API already matches reviewed Git source, HTTP liveness and manual deployment policy. No deployment triggered."
    if mode == "inspect":
        raise ReconcileError("Existing Render beta API source or HTTP liveness differs from reviewed Blueprint; no changes applied")
    # Update only source branch, manual-deploy policy and the declared HTTP
    # liveness path. Secrets, datastores, plans and deploys are untouched.
    client.patch_source(service_id, manifest)
    final = client.get(service_id)
    verify_identity(final, service_id=service_id, workspace_id=workspace_id, manifest=manifest)
    if (
        final.get("branch") != manifest.branch
        or _trigger(final) != "off"
        or _health_check_path(final) != manifest.health_check_path
    ):
        raise ReconcileError("Render API did not confirm source reconciliation")
    return "Existing Render beta API tracks reviewed main with auto-deploy off and HTTP liveness configured. No deployment triggered."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely reconcile the existing Render beta API Git source")
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("inspect", "apply"), default="inspect")
    args = parser.parse_args(argv)
    try:
        manifest = Manifest.read(args.manifest)
        # Never echo this value or include it in an error message.
        token = os.environ.get("RENDER_API_KEY", "")
        client = RenderClient(token)
        message = reconcile(
            client=client,
            service_id=args.service_id,
            workspace_id=args.workspace_id,
            manifest=manifest,
            mode=args.mode,
        )
    except (ReconcileError, OSError) as exc:
        if isinstance(exc, OSError):
            print("FAILED: Cannot read the checked-in Render Blueprint", file=sys.stderr)
        else:
            print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
