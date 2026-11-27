"""Run the signed-session Communications lifecycle on the existing isolated smoke stack."""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "scripts/ci/communications_browser_fixture.py"
UI = ROOT / "src/ui_launchers/Karen-AI-Theme"

# Only fixed vocabulary and numeric source positions may leave the private
# report. Never print a Playwright error, stdout, request or response body.
_STAGE = "admission"
_SCENARIOS = {
    "KCOMM-02E: real signed-session recovery, lifecycle persistence and account isolation": "KCOMM-02E",
    "KCOMM-03G: committed change delivery, cancellation and live session revocation": "KCOMM-03G",
}
_STATUSES = {"passed", "failed", "timedOut", "skipped", "interrupted", "expected", "unexpected", "flaky"}
_HINT_FAILURES = {
    "none", "proxy_unavailable", "redirect_rejected", "invalidation_unavailable",
    "session_unavailable", "auth_required", "permission_denied", "other",
    "inbox_unavailable", "authentication_unavailable", "rate_limit_unavailable",
    "backend_not_configured", "serialization_failed", "unclassified_body",
}
_BACKEND_EVENTS = {
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.wait_unavailable"): "wait_unavailable",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.wait_admitted"): "wait_admitted",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.wait_signal_observed"): "wait_signal_observed",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.wait_idle"): "wait_idle",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.wait_cancelled"): "wait_cancelled",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.unavailable"): "publish_unavailable",
    ("ai_karen_engine.core.realtime.inbox_invalidation", "communications.invalidation.broker_acknowledged"): "broker_acknowledged",
    ("ai_karen_engine.services.communications_inbox", "communications.invalidation.wait_completed"): "wait_completed",
    ("ai_karen_engine.api_routes.content.communications", "communications.inbox.unavailable"): "inbox_unavailable",
    ("ai_karen_engine.server.routers", "Authentication service unavailable"): "authentication_unavailable",
    ("ai_karen_engine.server.routers", "Authentication rejected request"): "authentication_rejected",
    ("ai_karen_engine.server.exception_handlers", "Failed to serialize exception response"): "serialization_failed",
    ("ai_karen_engine.server.exception_handlers", "Authentication request rejected"): "authentication_rejected",
}
_SAFE_ERROR_TYPES = {
    "InboxInvalidationUnavailable", "AuthenticationError", "HTTPException",
    "RuntimeError", "TimeoutError", "ConnectionError", "ConnectionResetError",
    "AttributeError", "TypeError", "ValueError", "PermissionError", "OSError",
    "InvalidStateError", "RedisError", "ResponseError", "OperationalError",
    "InterfaceError", "DBAPIError", "MissingGreenlet",
}
_WAIT_REASONS = {
    "configuration", "manager_unavailable", "owner_scope", "duplicate_owner",
    "capacity", "disconnect_check", "client_disconnected", "subscribe",
    "subscribe_ack", "broker_receive", "unexpected_frame", "subscription_cleanup",
}
_BODY_STATES = {"read_failed", "empty", "invalid_json", "json"}
_BROWSER_STAGES = {
    "login", "prior_wait_cleanup", "initial_projection", "broker_admission", "commit_read",
    "hint_order", "foreign_idle", "cancel", "reopen", "revoke",
    "revoked_signal", "cleanup",
}


def stage(name):
    global _STAGE
    _STAGE = name


def safe_correlation(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        return None
    return value.lower()


def report_failure_summary(report):
    """Emit only fixed scenario/stage/status tokens and numeric spec locations."""
    def safe_status(value):
        return value if isinstance(value, str) and value in _STATUSES else "unknown"

    correlations = set()

    def visit(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                scenario = _SCENARIOS.get(spec.get("title"), "unknown")
                for test in spec.get("tests", []):
                    status = safe_status(test.get("status"))
                    stages = [
                        item.get("description") for item in test.get("annotations", [])
                        if item.get("type") == "kcomm-stage"
                        and item.get("description") in _BROWSER_STAGES
                    ]
                    last = stages[-1] if stages else "unknown"
                    print(f"KCOMM_BROWSER_DIAGNOSTIC scenario={scenario} status={status} stage={last}")
                    for item in test.get("annotations", []):
                        value = item.get("description")
                        if item.get("type") == "kcomm-hint-http" and isinstance(value, str) and re.fullmatch(r"[1-5][0-9]{2}", value):
                            print("KCOMM_BROWSER_HINT_HTTP status=" + value)
                        if item.get("type") == "kcomm-hint-failure" and isinstance(value, str) and value in _HINT_FAILURES:
                            print("KCOMM_BROWSER_HINT_FAILURE kind=" + value)
                        if item.get("type") == "kcomm-hint-body-state" and isinstance(value, str) and value in _BODY_STATES:
                            print("KCOMM_BROWSER_HINT_BODY state=" + value)
                        if scenario == "KCOMM-03G" and item.get("type") == "kcomm-revoked-http" and isinstance(value, str) and re.fullmatch(r"[1-5][0-9]{2}", value):
                            print("KCOMM_BROWSER_REVOKED_HTTP status=" + value)
                        if scenario == "KCOMM-03G" and item.get("type") == "kcomm-revoked-body" and isinstance(value, str) and value in {"json", "read_failed"}:
                            print("KCOMM_BROWSER_REVOKED_BODY state=" + value)
                        if item.get("type") == "kcomm-hint-request-failed" and value == "yes":
                            print("KCOMM_BROWSER_HINT_REQUEST_FAILED observed=yes")
                        if scenario == "KCOMM-03G" and item.get("type") == "kcomm-hint-correlation":
                            correlation = safe_correlation(value)
                            if correlation:
                                correlations.add(correlation)
                    for result in test.get("results", []):
                        print("KCOMM_BROWSER_RESULT status=" + safe_status(result.get("status")))
                        positions = set()
                        for error in result.get("errors", []):
                            # Match the fixed spec basename, not arbitrary paths
                            # or stack content. Never output the original string.
                            stack = error.get("stack")
                            if isinstance(stack, str):
                                for line, column in re.findall(
                                    r"comms-visual-acceptance\.spec\.ts:(\d{1,5}):(\d{1,5})", stack,
                                ):
                                    positions.add((int(line), int(column)))
                            location = error.get("location")
                            if (
                                isinstance(location, dict)
                                and isinstance(location.get("file"), str)
                                and Path(location["file"]).name == "comms-visual-acceptance.spec.ts"
                                and type(location.get("line")) is int and 1 <= location["line"] <= 99999
                                and type(location.get("column")) is int and 1 <= location["column"] <= 99999
                            ):
                                positions.add((location["line"], location["column"]))
                        for line, column in sorted(positions)[:8]:
                            print(f"KCOMM_BROWSER_ASSERTION line={line} column={column}")
            visit(suite.get("suites", []))

    visit(report.get("suites", []))
    return correlations


def report_backend_failure_summary(logs, correlations=None, *, structured=False):
    """Emit only known backend event labels; never copy raw logs or identities.

    Without a correlation filter this is an aggregate, not a per-request trace.
    With a filter, accept only exact structured correlation matches.
    """
    counts = {}
    trace_tags = {
        hashlib.sha256(value.encode("ascii")).hexdigest()
        for value in (correlations or ())
        if safe_correlation(value) == value
    }
    for line in logs.splitlines():
        name = message = error_type = reason = correlation = None
        try:
            entry = json.loads(line)
        except (TypeError, ValueError):
            entry = None
        if isinstance(entry, dict):
            name, message, error_type = (
                entry.get("name") or entry.get("logger"), entry.get("message"), entry.get("error_type")
            )
            reason = entry.get("reason")
            correlation = safe_correlation(entry.get("correlation_id"))
        else:
            parts = line.split(" - ", 3)
            if len(parts) == 4:
                _, name, level, message = parts
                if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                    continue
        if not isinstance(name, str) or not isinstance(message, str):
            continue
        trace_tag = None
        if name == "ai_karen_engine.core.realtime.inbox_invalidation":
            match = re.fullmatch(
                r"(communications\.invalidation\.wait_[a-z_]+(?: reason=[a-z_]+)?) trace=([0-9a-f]{64})",
                message,
            )
            if match:
                message, trace_tag = match.groups()
            prefix = "communications.invalidation.wait_unavailable reason="
            if message.startswith(prefix):
                candidate = message[len(prefix):]
                if candidate in _WAIT_REASONS:
                    reason = candidate
                    message = "communications.invalidation.wait_unavailable"
        if correlations is not None and correlation not in correlations and trace_tag not in trace_tags:
            continue
        kind = _BACKEND_EVENTS.get((name, message))
        if name == "ai_karen_engine.middleware.rate_limit":
            prefix = "Rate limit enforcement unavailable: "
            if message.startswith(prefix):
                kind = "rate_limit_unavailable"
                error_type = message[len(prefix):]
        if kind is None:
            continue
        safe_type = (
            error_type
            if isinstance(error_type, str) and error_type in _SAFE_ERROR_TYPES
            else "unknown"
        )
        safe_reason = reason if isinstance(reason, str) and reason in _WAIT_REASONS else "unknown"
        key = (kind, safe_type, safe_reason)
        counts[key] = counts.get(key, 0) + 1
    label = (
        "KCOMM_STRUCTURED_BACKEND_EVENT" if structured
        else "KCOMM_CORRELATED_BACKEND_EVENT" if correlations is not None
        else "KCOMM_BACKEND_EVENT"
    )
    if not counts:
        print(label + "S status=none_observed")
    for (kind, error_type, reason), count in sorted(counts.items()):
        print(f"{label} kind={kind} error_type={error_type} count={count} reason={reason}")


def collect_backend_failure_summary(container, started, correlations=()):
    """Best effort on the already verified disposable API container only."""
    try:
        result = subprocess.run(
            ["docker", "logs", "--since", str(started), "--tail", "2000", container],
            capture_output=True, text=True, errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("KCOMM_BACKEND_EVENTS status=unavailable")
        return
    if result.returncode:
        print("KCOMM_BACKEND_EVENTS status=unavailable")
        return
    report_backend_failure_summary(result.stdout + "\n" + result.stderr)
    if not correlations:
        print("KCOMM_CORRELATED_BACKEND_EVENTS status=missing_browser_correlation")
        return
    # The real API console is the observed sink in first-boot. Match its
    # fixed event tags or JSON correlation fields before consulting the file.
    report_backend_failure_summary(result.stdout + "\n" + result.stderr, correlations=set(correlations))
    # Existing structured log sink; never print raw records or IDs.
    try:
        structured = subprocess.run(
            ["docker", "exec", container, "tail", "-n", "4000", "logs/kari.log"],
            capture_output=True, text=True, errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("KCOMM_STRUCTURED_BACKEND_EVENTS status=unavailable")
        return
    if structured.returncode:
        print("KCOMM_STRUCTURED_BACKEND_EVENTS status=unavailable")
        return
    report_backend_failure_summary(structured.stdout, correlations=set(correlations), structured=True)


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
    parser.add_argument("--observe-owner", action="append")
    parser.add_argument("--expected-count", type=int, choices=(0, 1))
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
    if args.observe_owner is not None or args.expected_count is not None:
        if not args.observe_owner or args.expected_count is None:
            raise RuntimeError("Incomplete broker witness request")
        owners = [str(uuid.UUID(owner)) for owner in args.observe_owner]
        receipt = fixture(args.api_container, {
            "mode": "observe_subscribers", "tenant_id": tenant,
            "owners": owners, "expected_count": args.expected_count,
        })
        if receipt != {"subscriber_counts": [args.expected_count] * len(owners)}:
            raise RuntimeError("Unexpected broker witness receipt")
        print("DISPOSABLE COMMUNICATIONS BROKER WITNESS PASSED")
        return
    stage("fixture_accounts")
    accounts = [account(), account()]
    user_ids = fixture(args.api_container, {"mode": "accounts", "tenant_id": tenant, "accounts": accounts})["users"]
    stage("fixture_signed_login")
    identities = []
    for acct, user_id in zip(accounts, user_ids, strict=True):
        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = json.loads(request(opener, origin, "/api/auth/login", acct))
        user = login["user"]
        if user["user_id"] != user_id or user["tenant_id"] != tenant or user["roles"] != ["user"]:
            raise RuntimeError("Signed fixture principal mismatch")
        conversation = json.loads(request(opener, origin, "/api/conversations/ensure-session/" + str(uuid.uuid4()), {}))
        identities.append({"user_id": user_id, "conversation_id": str(uuid.UUID(conversation["id"]))})
    stage("fixture_runtime_rows")
    runs = fixture(args.api_container, {"mode": "runs", "tenant_id": tenant, "identities": identities})["executions"]
    if len(runs) != 2 or runs[0] == runs[1]:
        raise RuntimeError("Distinct runtime fixture receipts required")
    stage("web_start")
    web_container = "karen-beta-comms-web-" + uuid.uuid4().hex
    web_origin = isolated_origin("http://127.0.0.1:18010")
    try:
        subprocess.run([
            "docker", "run", "-d", "--name", web_container, "--network", args.network,
            "-p", "127.0.0.1:18010:8010", "-e", "WEB_PUBLIC_SCHEME=http",
            "-e", "KAREN_BACKEND_URL=http://" + args.api_container + ":8000", "ai-karen-web:beta",
        ], check=True, stdout=subprocess.DEVNULL, timeout=60)
        stage("web_readiness")
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
               "KAREN_COMMS_INVALIDATION_ACCEPTANCE": "true",
               "KAREN_COMMS_WITNESS_PYTHON": sys.executable,
               "KAREN_COMMS_WITNESS_API_CONTAINER": args.api_container,
               "KAREN_COMMS_WITNESS_NETWORK": args.network,
               "KAREN_COMMS_WITNESS_API_URL": origin,
               "KAREN_COMMS_WITNESS_TENANT": tenant,
               "KAREN_COMMS_WITNESS_OWNER_A": user_ids[0],
               "KAREN_COMMS_WITNESS_OWNER_B": user_ids[1],
               "KAREN_UX_EMAIL": accounts[0]["email"], "KAREN_UX_PASSWORD": accounts[0]["password"],
               "KAREN_UX_ACCOUNT_B_EMAIL": accounts[1]["email"], "KAREN_UX_ACCOUNT_B_PASSWORD": accounts[1]["password"],
               "KAREN_UX_ACCOUNT_A_PENDING_INBOX_EXECUTION_ID": runs[0],
               "KAREN_UX_ACCOUNT_B_INBOX_EXECUTION_ID": runs[1]}
        # Use a private ephemeral report to reject no-op/skip success, never
        # upload or print browser diagnostic bodies or fixture credentials.
        stage("chromium_execution")
        with tempfile.TemporaryDirectory(prefix="kcomm-browser-") as directory:
            private = Path(directory)
            report_path = private / "report.json"
            env["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(report_path)
            browser_started = int(time.time())
            with (private / "runner.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([
                    "npx", "--no-install", "playwright", "test", "e2e/comms-visual-acceptance.spec.ts",
                    "--config=e2e/playwright.config.ts", "--project=chromium",
                    "--reporter=json", "--workers=1", "--retries=0", "--forbid-only",
                    "--grep=KCOMM-02E|KCOMM-03G", "--output=" + str(private / "artifacts"),
                ], cwd=UI, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=420)
            if not report_path.is_file():
                collect_backend_failure_summary(args.api_container, browser_started)
                stage("chromium_report_missing")
                raise RuntimeError("Disposable Chromium report missing")
            stage("chromium_report_validation")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if result.returncode != 0:
                correlations = report_failure_summary(report)
                collect_backend_failure_summary(args.api_container, browser_started, correlations)
                raise RuntimeError("Disposable Chromium scenario failed; private diagnostics suppressed")
            stats = report.get("stats", {})
            if report.get("errors") != [] or stats.get("expected") != 2 or any(
                stats.get(key) != 0 for key in ("unexpected", "skipped", "flaky")
            ):
                report_failure_summary(report)
                raise RuntimeError("Exactly two passing browser scenarios without skips or retries required")
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
            ), (
                "KCOMM-03G: committed change delivery, cancellation and live session revocation",
                "expected", "passed", "chromium", ["passed"],
            )]:
                report_failure_summary(report)
                raise RuntimeError("Incorrect browser acceptance inventory")
        print("DISPOSABLE COMMUNICATIONS SIGNED-SESSION LIFECYCLE PROOF PASSED: one test, zero skips or retries")
        print("DISPOSABLE COMMUNICATIONS SIGNED-SESSION INVALIDATION PROOF PASSED: one test, zero skips or retries")
    finally:
        subprocess.run(["docker", "rm", "-f", web_container], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=30)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exception tracebacks can contain request/response details.
        print("Disposable Communications proof failed: " + type(exc).__name__ + " stage=" + _STAGE)
        raise SystemExit(1) from None
