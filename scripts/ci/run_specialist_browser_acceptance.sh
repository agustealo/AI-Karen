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
# Select one reviewed scenario; a fresh trial is Docker-only and must
# never satisfy the existing seeded lifecycle/cross-tenant readback gate.
export KAREN_SEARCH_ACCEPTANCE_REQUIRED=true
mode="${2:-readback}"
case "$mode" in
  readback)
    title='ARM-05C.5B real participation receipts survive reload and deny a second account'
    for flag in KAREN_SPECIALIST_PARTICIPATION_ACCEPTANCE KAREN_SPECIALIST_LIFECYCLE_ACCEPTANCE KAREN_SPECIALIST_CROSS_TENANT_ACCEPTANCE; do
      test "${!flag:-}" = true || { echo "::error::Full specialist acceptance flags are required"; exit 1; }
    done
    required=(KAREN_UX_EMAIL KAREN_UX_PASSWORD KAREN_UX_ACCOUNT_B_EMAIL KAREN_UX_ACCOUNT_B_PASSWORD KAREN_UX_ACCOUNT_C_EMAIL KAREN_UX_ACCOUNT_C_PASSWORD KAREN_UX_ACCOUNT_A_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_B_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_A_EMPTY_PARTICIPATION_RUN_ID KAREN_UX_ACCOUNT_C_PARTICIPATION_RUN_ID)
    ;;
  fresh)
    test "$1" = docker && test "${KAREN_SPECIALIST_FRESH_ACCEPTANCE:-}" = true || { echo "::error::Fresh specialist acceptance requires explicit signed Docker mode"; exit 1; }
    title='ARM-05C.8C fresh specialist execution survives reload'
    required=(KAREN_UX_EMAIL KAREN_UX_PASSWORD KAREN_SPECIALIST_EXPECTED_PROVIDER KAREN_SPECIALIST_EXPECTED_MODEL KAREN_SPECIALIST_EXPECTED_ENGINE)
    ;;
  *) echo "::error::Unsupported specialist scenario"; exit 1 ;;
esac
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "::error::Missing protected specialist fixture configuration"; exit 1; }
done
private_dir="$(mktemp -d "${RUNNER_TEMP:?}/specialist-acceptance.XXXXXXXX")"
trap 'rm -rf -- "$private_dir"' EXIT
# Never publish private Playwright diagnostics or even a failed report.
# An ephemeral report is used solely to reject skipped/no-op success.
if ! PLAYWRIGHT_JSON_OUTPUT_FILE="$private_dir/report.json" \
  npx playwright test e2e/automation-two-account-acceptance.spec.ts \
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
    "fresh": "ARM-05C.8C fresh specialist execution survives reload",
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
echo "Protected specialist acceptance: one passing scenario, zero skips"
