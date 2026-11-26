#!/usr/bin/env bash
set -euo pipefail
umask 077
# Shared private gate; never expose Vercel authorization to Docker.
case "${1:-}" in
  vercel)
    test -n "${VERCEL_AUTOMATION_BYPASS_SECRET:-}" || { echo "::error::Missing protected deployment authorization"; exit 1; }
    ;;
  docker)
    if [[ -v VERCEL_AUTOMATION_BYPASS_SECRET ]]; then
      echo "::error::Docker specialist acceptance must not receive Vercel authorization"
      exit 1
    fi
    ;;
  *) echo "::error::Unsupported specialist acceptance platform"; exit 1 ;;
esac
export KAREN_SEARCH_ACCEPTANCE_PLATFORM="$1"
# Always activate the existing exact-origin deployment fixture.
export KAREN_SEARCH_ACCEPTANCE_REQUIRED=true
mode="${2:-readback}"
case "$mode" in
  readback)
    # Exactly one pass alone does not establish full lifecycle and isolation.
    for flag in KAREN_SPECIALIST_PARTICIPATION_ACCEPTANCE KAREN_SPECIALIST_LIFECYCLE_ACCEPTANCE KAREN_SPECIALIST_CROSS_TENANT_ACCEPTANCE; do
      test "${!flag:-}" = true || { echo "::error::Full specialist acceptance flags are required"; exit 1; }
    done
    for name in KAREN_UX_EMAIL KAREN_UX_PASSWORD KAREN_UX_ACCOUNT_B_EMAIL KAREN_UX_ACCOUNT_B_PASSWORD KAREN_UX_ACCOUNT_C_EMAIL KAREN_UX_ACCOUNT_C_PASSWORD KAREN_UX_ACCOUNT_A_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_B_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_A_EMPTY_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_C_PARTICIPATION_RUN_ID; do
      test -n "${!name:-}" || { echo "::error::Missing protected specialist fixture configuration"; exit 1; }
    done
    spec='e2e/automation-two-account-acceptance.spec.ts'
    title='ARM-05C.5B real participation receipts survive reload and deny a second account'
    ;;
  ordinary-chat)
    test "$1" = docker || { echo "::error::Ordinary specialist trial requires signed Docker"; exit 1; }
    test "${KAREN_SPECIALIST_ORDINARY_CHAT_ACCEPTANCE:-}" = true &&
      test "${KAREN_SPECIALIST_ORDINARY_CHAT_APPROVED:-}" = true &&
      test "${KAREN_CHAT_BOOT_ACCEPTANCE:-}" = 1 ||
      { echo "::error::Explicit disposable ordinary-chat approval is required"; exit 1; }
    for name in KAREN_UX_EMAIL KAREN_UX_PASSWORD KAREN_CHAT_BOOT_REVISION KAREN_SPECIALIST_ORDINARY_CHAT_TENANT_ID KAREN_SPECIALIST_ORDINARY_CHAT_USER_ID KAREN_SPECIALIST_ORDINARY_CHAT_PROMPT KAREN_SPECIALIST_EXPECTED_PROVIDER KAREN_SPECIALIST_EXPECTED_MODEL KAREN_SPECIALIST_EXPECTED_ENGINE KAREN_SPECIALIST_EXPECTED_AGENT KAREN_SPECIALIST_EXPECTED_TOOL; do
      test -n "${!name:-}" || { echo "::error::Missing protected ordinary-chat configuration"; exit 1; }
    done
    [[ "$KAREN_CHAT_BOOT_REVISION" =~ ^[a-f0-9]{40}$ ]] ||
      { echo "::error::Exact reviewed revision required"; exit 1; }
    spec='e2e/copilotkit-consumer-boot.spec.ts'
    title='ARM-08 fresh ordinary-chat specialist execution survives reload'
    ;;
  *) echo "::error::Unsupported specialist acceptance scenario"; exit 1 ;;
esac
test "$#" -le 2 || { echo "::error::Unexpected specialist acceptance arguments"; exit 1; }
private_dir="$(mktemp -d "${RUNNER_TEMP:?}/specialist-acceptance.XXXXXXXX")"
trap 'rm -rf -- "$private_dir"' EXIT
# Never publish private Playwright diagnostics or even a failed report.
# An ephemeral report is used solely to reject skipped/no-op success.
if ! PLAYWRIGHT_JSON_OUTPUT_FILE="$private_dir/report.json" \
  npx playwright test "$spec" \
    --config=e2e/playwright.config.ts --project=chromium \
    --grep="$title" \
    --workers=1 --retries=0 --forbid-only --reporter=json \
    --output="$private_dir/artifacts" >"$private_dir/runner.log" 2>&1; then
  echo "::error::Protected specialist browser acceptance failed (private diagnostics suppressed)"
  exit 1
fi
if ! python - "$private_dir/report.json" "$mode" 2>/dev/null <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
stats = report.get("stats", {})
if report.get("errors") != [] or stats.get("expected") != 1 or any(
    stats.get(key) != 0 for key in ("unexpected", "skipped", "flaky")
):
    raise SystemExit(1)
observed = []
def collect(suites):
    for suite in suites:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                observed.append((spec.get("title"), test.get("status"),
                                 test.get("expectedStatus"),
                                 test.get("projectName"),
                                 [r.get("status") for r in test.get("results", [])]))
        collect(suite.get("suites", []))
collect(report.get("suites", []))
title = {
    "readback": "ARM-05C.5B real participation receipts survive reload and deny a second account",
    "ordinary-chat": "ARM-08 fresh ordinary-chat specialist execution survives reload",
}.get(sys.argv[2])
if title is None or observed != [(
    title,
    "expected", "passed", "chromium", ["passed"],
)]:
    raise SystemExit(1)
PY
then
  echo "::error::Exactly one passing real specialist scenario is required"
  exit 1
fi
if [[ "${2:-readback}" == ordinary-chat ]]; then
  echo "Protected ordinary-chat specialist acceptance: one passing scenario, zero skips"
else
  echo "Protected specialist readback: one passing scenario, zero skips"
fi
