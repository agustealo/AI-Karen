#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Execute on an approved KAREN host against a clean, exact SHA checkout.
EXPECTED_SHA="${1:?Usage: bash scripts/ci/kui-local-acceptance.sh <40-character-SHA>}"
if [[ ! "$EXPECTED_SHA" =~ ^[[:xdigit:]]{40}$ ]]; then
  echo 'Expected SHA must contain 40 hexadecimal characters.' >&2
  exit 2
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]] || [[ -n "$(git status --porcelain)" ]]; then
  echo 'Expected exact HEAD and a clean worktree.' >&2
  exit 2
fi

# Real browser acceptance is explicitly opted in, never inferred from CI.
if [[ "${RUN_BROWSER:-0}" == '1' ]]; then
  : "${KAREN_UX_EMAIL:?Dedicated sanitized test email required}"
  : "${KAREN_UX_PASSWORD:?Dedicated sanitized test password required}"
  : "${KAREN_BASE_URL:?Approved browser origin required}"
  case "$KAREN_BASE_URL" in
    http://127.0.0.1:*|http://localhost:*)
      if [[ "${KAREN_LOCAL_CHAT_ACCEPTANCE:-0}" != '1' ]]; then
        echo 'Local loopback requires KAREN_LOCAL_CHAT_ACCEPTANCE=1.' >&2
        exit 2
      fi
      ;;
    https://*) ;;
    *) echo 'Refusing browser credentials on unapproved origin.' >&2; exit 2 ;;
  esac
  if [[ "${KAREN_PLUGINS_SANITIZED_CAPTURE:-false}" == 'true' &&
        "${KAREN_SANITIZED_ACCOUNT:-false}" != 'true' ]]; then
    echo 'Screenshot evidence requires a dedicated sanitized identity.' >&2
    exit 2
  fi
fi

# Authenticated reports may contain live metadata. Keep outside the checkout.
OUT="${KAREN_KUI_ACCEPTANCE_OUTPUT_DIR:-${XDG_STATE_HOME:-${HOME:?}/.local/state}/ai-karen/kui-acceptance/$ACTUAL_SHA}"
mkdir -p "$OUT"
RESULTS="$OUT/results.txt"
printf 'SHA=%s\nDATE=%s\nRUN_BROWSER=%s\n' \
  "$ACTUAL_SHA" "$(date -u +'%FT%TZ')" "${RUN_BROWSER:-0}" >"$RESULTS"

run() {
  local name="$1"; shift
  printf '>>> %s\n' "$name"
  if "$@" >"$OUT/$name.log" 2>&1; then
    printf 'PASS %s\n' "$name" | tee -a "$RESULTS"
  else
    local code=$?
    printf 'FAIL %s (%s; log %s)\n' "$name" "$code" "$OUT/$name.log" | tee -a "$RESULTS"
    return "$code"
  fi
}

run python_compile python -m compileall -q src
run backend_scope pytest -q tests/api_routes/test_communications_center_scope.py

cd "$ROOT/src/ui_launchers/Karen-AI-Theme"
run npm_install npm ci
run lint npm run lint
run typecheck npm run typecheck
run plugin_ui_tests npx vitest run src/components/plugins/PluginOverviewPage.test.tsx
run communications_ui_tests npx vitest run src/components/comms/CommsCenterPage.test.tsx
run next_build npm run build

if [[ "${RUN_BROWSER:-0}" == '1' ]]; then
  run chromium_install npx playwright install chromium
  run plugins_live_browser env \
    KAREN_PLUGINS_VISUAL_ACCEPTANCE=true \
    PLAYWRIGHT_JSON_OUTPUT_FILE="$OUT/plugins-playwright.json" \
    npx playwright test e2e/plugins-visual-acceptance.spec.ts \
      --config=e2e/playwright.config.ts --project=chromium \
      --workers=1 --retries=0 --forbid-only --reporter=json \
      --output="$OUT/playwright-artifacts"

  # Playwright can return success for skipped tests. Require one real pass.
  run plugins_browser_evidence python - "$OUT/plugins-playwright.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("No browser report")
report = json.loads(path.read_text())
stats = report.get("stats", {})
if stats.get("expected") != 1 or any(
    stats.get(key, 0) for key in ("unexpected", "skipped", "flaky")
):
    raise SystemExit("Browser acceptance was not one clean passing test")

observed = []
def collect(suites):
    for suite in suites:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                observed.append((test.get("status"), test.get("expectedStatus")))
        collect(suite.get("suites", []))

collect(report.get("suites", []))
if observed != [("expected", "passed")]:
    raise SystemExit("Browser test did not complete as expected")
print("One real authenticated Plugins & Tools browser acceptance passed")
PY
else
  printf 'NOT_RUN plugins_live_browser (RUN_BROWSER=1 required)\n' | tee -a "$RESULTS"
fi

printf 'NOT_VERIFIED visual pixel parity and release readiness require independent review.\n' | tee -a "$RESULTS"
printf 'RESULTS=%s\n' "$RESULTS"
