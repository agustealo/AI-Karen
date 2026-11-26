"""Run the signed-session Communications lifecycle on the existing isolated smoke stack."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "scripts/ci/communications_browser_fixture.py"
UI = ROOT / "src/ui_launchers/Karen-AI-Theme"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def isolated_origin(url: str) -> str:
    value = urlsplit(url)
    if (
        value.scheme != "http" or value.hostname != "127.0.0.1"
        or not value.port or value.username or value.password
        or value.path not in ("", "/") or value.query or value.fragment
    ):
        raise RuntimeError("Only explicitly isolated loopback origin allowed")
    return f"http://127.0.0.1:{value.port}"


def request(opener, origin, path, payload=None):
    if not path.startswith("/api/") and path != "/login":
        raise RuntimeError("Unexpected fixture endpoint")
    req = Request(origin + path, data=None if payload is None else json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, method="GET" if payload is None else "POST")
    with opener.open(req, timeout=30) as response:
        if response.status not in (200, 201):
            raise RuntimeError("Unexpected fixture HTTP result")
        return response.read()


def fixture(container, data):
    env = {**os.environ, "KAREN_COMMS_FIXTURE_INPUT": json.dumps(data)}
    process = subprocess.run(
        ["docker", "exec", "-i", "--env", "KAREN_COMMS_FIXTURE_INPUT", container, "python", "-"],
        input=FIXTURE.read_text(encoding="utf-8"), text=True,
        capture_output=True, env=env, timeout=120, check=False,
    )
    if process.returncode:
        # Do not emit captured logs containing user input or credentials.
        failures = [line for line in process.stderr.splitlines() if line.startswith("KCOMM_FIXTURE_FAILED=")]
        raise RuntimeError("Disposable fixture setup failed " + (failures[-1] if failures else "before receipt"))
    receipts = [line for line in process.stdout.splitlines() if line.startswith("KCOMM_FIXTURE_RESULT=")]
    if len(receipts) != 1:
        raise RuntimeError("Missing unique fixture receipt")
    return json.loads(receipts[0].split("=", 1)[1])


def account():
    return {"email": "kcomm-smoke-" + uuid.uuid4().hex + "@example.invalid",
            "password": "T9!a" + secrets.token_urlsafe(24)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-container", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    if os.environ.get("KAREN_SMOKE_COMMS_BROWSER_PROOF") != "true":
        raise RuntimeError("Explicit disposable smoke opt-in required")
    if not args.api_container.startswith("karen-beta-api-") or not args.network.startswith("karen-beta-smoke-"):
        raise RuntimeError("Refusing non-smoke containers")
    if args.api_container.removeprefix("karen-beta-api-") != args.network.removeprefix("karen-beta-smoke-"):
        raise RuntimeError("Mismatched smoke identities")
    origin = isolated_origin(args.api_url)
    tenant = str(uuid.UUID(args.tenant_id))
    # Confirm the exact running container is joined to this disposable network.
    inspected = json.loads(subprocess.check_output(["docker", "inspect", args.api_container], text=True))[0]
    if args.network not in inspected["NetworkSettings"]["Networks"]:
        raise RuntimeError("Smoke container is not on isolated network")
    binding = inspected["NetworkSettings"]["Ports"].get("8000/tcp") or []
    if not any(b["HostIp"] == "127.0.0.1" and b["HostPort"] == str(urlsplit(origin).port) for b in binding):
        raise RuntimeError("API host binding is not the isolated smoke container")
    accounts = [account(), account()]
    user_ids = fixture(args.api_container, {"mode": "accounts", "tenant_id": tenant, "accounts": accounts})["users"]
    identities = []
    for acct, user_id in zip(accounts, user_ids, strict=True):
        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = json.loads(request(opener, origin, "/api/auth/login", acct))
        user = login["user"]
        if user["user_id"] != user_id or user["tenant_id"] != tenant or user["roles"] != ["user"]:
            raise RuntimeError("Signed fixture principal mismatch")
        conversation = json.loads(request(opener, origin, "/api/conversations/ensure-session/" + str(uuid.uuid4()), {}))
        identities.append({"user_id": user_id, "conversation_id": str(uuid.UUID(conversation["id"]))})
    runs = fixture(args.api_container, {"mode": "runs", "tenant_id": tenant, "identities": identities})["executions"]
    if len(runs) != 2 or runs[0] == runs[1]:
        raise RuntimeError("Distinct runtime fixture receipts required")
    web_container = "karen-beta-comms-web-" + uuid.uuid4().hex
    web_origin = isolated_origin("http://127.0.0.1:18010")
    try:
        subprocess.run([
            "docker", "run", "-d", "--name", web_container, "--network", args.network,
            "-p", "127.0.0.1:18010:8010", "-e", "WEB_PUBLIC_SCHEME=http",
            "-e", "KAREN_BACKEND_URL=http://" + args.api_container + ":8000", "ai-karen-web:beta",
        ], check=True, stdout=subprocess.DEVNULL, timeout=60)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                request(opener, web_origin, "/login")
                state = json.loads(request(opener, web_origin, "/api/auth/first-run"))
                if isinstance(state, dict):
                    break
            except (OSError, ValueError):
                time.sleep(2)
        else:
            raise RuntimeError("Disposable web/backend readiness failed")
        env = {**os.environ,
               "CI": "true", "KAREN_BASE_URL": web_origin,
               "KAREN_LOCAL_CHAT_ACCEPTANCE": "1", "KAREN_CHAT_BOOT_ACCEPTANCE": "0",
               "KAREN_COMMS_INBOX_ACCEPTANCE": "true", "KAREN_COMMS_VISUAL_ACCEPTANCE": "false",
               "KAREN_UX_EMAIL": accounts[0]["email"], "KAREN_UX_PASSWORD": accounts[0]["password"],
               "KAREN_UX_ACCOUNT_B_EMAIL": accounts[1]["email"], "KAREN_UX_ACCOUNT_B_PASSWORD": accounts[1]["password"],
               "KAREN_UX_ACCOUNT_A_PENDING_INBOX_EXECUTION_ID": runs[0],
               "KAREN_UX_ACCOUNT_B_INBOX_EXECUTION_ID": runs[1]}
        # Use a private ephemeral report to reject no-op/skip success, never
        # upload or print browser diagnostic bodies or fixture credentials.
        with tempfile.TemporaryDirectory(prefix="kcomm-browser-") as directory:
            private = Path(directory)
            report_path = private / "report.json"
            env["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(report_path)
            with (private / "runner.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([
                    "npx", "--no-install", "playwright", "test", "e2e/comms-visual-acceptance.spec.ts",
                    "--config=e2e/playwright.config.ts", "--project=chromium",
                    "--reporter=json", "--workers=1", "--retries=0", "--forbid-only",
                    "--grep=KCOMM-02E", "--output=" + str(private / "artifacts"),
                ], cwd=UI, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=420)
            if result.returncode != 0 or not report_path.is_file():
                raise RuntimeError("Disposable Chromium scenario failed; private diagnostics suppressed")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            stats = report.get("stats", {})
            if report.get("errors") != [] or stats.get("expected") != 1 or any(
                stats.get(key) != 0 for key in ("unexpected", "skipped", "flaky")
            ):
                raise RuntimeError("Exactly one passing browser scenario without skips or retries required")
            observed = []

            def collect(suites):
                for suite in suites:
                    for spec in suite.get("specs", []):
                        for test in spec.get("tests", []):
                            observed.append((spec.get("title"), test.get("status"),
                                             test.get("expectedStatus"), test.get("projectName"),
                                             [r.get("status") for r in test.get("results", [])]))
                    collect(suite.get("suites", []))

            collect(report.get("suites", []))
            if observed != [(
                "KCOMM-02E: real signed-session recovery, lifecycle persistence and account isolation",
                "expected", "passed", "chromium", ["passed"],
            )]:
                raise RuntimeError("Incorrect browser acceptance inventory")
        print("DISPOSABLE COMMUNICATIONS SIGNED-SESSION LIFECYCLE PROOF PASSED: one test, zero skips or retries")
    finally:
        subprocess.run(["docker", "rm", "-f", web_container], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=30)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exception tracebacks can contain request/response details.
        print("Disposable Communications proof failed: " + type(exc).__name__)
        raise SystemExit(1) from None
