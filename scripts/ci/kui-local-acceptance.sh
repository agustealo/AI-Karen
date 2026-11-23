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
  if [[ "${KAREN_PLUGINS_SANITIZED_CAPTURE:-true}" == 'true' &&
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
run ruff_check ruff check src tests scripts
run backend_scope pytest -q tests/api_routes/test_communications_center_scope.py
run card_studio_architecture pytest -q tests/architecture/test_card_studio_browser_acceptance_contract.py tests/architecture/test_kcard_local_acceptance_contract.py

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

if [[ "${RUN_CARD_STUDIO_LOCAL:-0}" == '1' ]]; then
  [[ "${KAREN_LOCAL_CHAT_ACCEPTANCE:-0}" == '1' ]] || { echo 'KAREN_LOCAL_CHAT_ACCEPTANCE=1 required.' >&2; exit 2; }
  [[ "${KAREN_CARD_STUDIO_LOCAL_ACCEPTANCE_REQUIRED:-false}" == 'true' ]] || { echo 'Dedicated local Card Studio guard required.' >&2; exit 2; }
  [[ "${KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE:-false}" == 'true' ]] || { echo 'Card Studio visual acceptance required.' >&2; exit 2; }
  [[ "${KAREN_CARD_STUDIO_MUTATION_APPROVED:-false}" == 'true' ]] || { echo 'Disposable Card Studio mutation approval required.' >&2; exit 2; }
  [[ "${KAREN_BASE_URL:-}" == 'http://127.0.0.1:8010' ]] || { echo 'Local Card Studio requires loopback base URL.' >&2; exit 2; }
  : "${KAREN_UX_EMAIL:?Dedicated sanitized owner email required}"
  : "${KAREN_UX_PASSWORD:?Dedicated sanitized owner password required}"
  : "${KAREN_UX_ISOLATION_EMAIL:?Dedicated sanitized isolation email required}"
  : "${KAREN_UX_ISOLATION_PASSWORD:?Dedicated sanitized isolation password required}"
  [[ "${KAREN_SANITIZED_ACCOUNT:-false}" == 'true' ]] || { echo 'Both credentials require sanitized-account approval.' >&2; exit 2; }
  [[ -z "${VERCEL_AUTOMATION_BYPASS_SECRET:-}" ]] || { echo 'Vercel bypass secret forbidden in local Card Studio acceptance.' >&2; exit 2; }
  [[ "${KAREN_SETTINGS_VERIFIED_DEPLOYMENT:-false}" != 'true' ]] || { echo 'Vercel-specific protected-deployment marker forbidden.' >&2; exit 2; }
  : "${KAREN_TEST_CARD_STUDIO_DATABASE_URL:?Disposable PostgreSQL DSN required}"
  : "${KAREN_TEST_CARD_STUDIO_AUTH_DATABASE_URL:?Disposable authentication PostgreSQL DSN required}"
  : "${KCARD_COMPOSE_PROJECT:?Disposable Card Studio Compose project required}"
  run card_studio_postgres_templates env KAREN_TEST_CARD_STUDIO_POSTGRES=1 pytest -q tests/integration/test_card_studio_templates_postgres.py
  run card_studio_postgres_signed_session env KAREN_TEST_CARD_STUDIO_POSTGRES=1 pytest -q tests/integration/test_card_studio_signed_session_postgres.py
  run card_studio_ui_tests npx vitest run src/components/card-studio/CardStudioWorkspace.test.tsx

  run card_studio_local_provenance_before python scripts/ci/verify_local_card_studio_acceptance.py \
    --sha "$ACTUAL_SHA" --project "$KCARD_COMPOSE_PROJECT" --base-url "$KAREN_BASE_URL" \
    --env-file "${KCARD_ACCEPTANCE_ENV_FILE:?Disposable acceptance env file required}" \
    --evidence "$OUT/card-studio-before.json"

  run card_studio_live_browser env \
    KAREN_CARD_STUDIO_LOCAL_ACCEPTANCE_REQUIRED=true \
    KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE=true \
    KAREN_CARD_STUDIO_MUTATION_APPROVED=true \
    KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
    KAREN_BASE_URL=http://127.0.0.1:8010 \
    PLAYWRIGHT_JSON_OUTPUT_FILE="$OUT/card-studio-playwright.json" \
    npx playwright test e2e/card-studio-live-acceptance.spec.ts \
      --config=e2e/playwright.config.ts --project=chromium \
      --workers=1 --retries=0 --forbid-only --reporter=json \
      --output="$OUT/card-studio-playwright-artifacts"

  run card_studio_live_evidence python - "$OUT/card-studio-playwright.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("No Card Studio browser report")
report = json.loads(path.read_text())
stats = report.get("stats", {})
for key in ("unexpected", "skipped", "flaky"):
    if stats.get(key, 0) != 0:
        raise SystemExit(f"Card Studio browser evidence contains {key}={stats[key]}")
if stats.get("expected") != 3:
    raise SystemExit("Card Studio browser evidence did not execute exactly three scenarios")
observed = []
def collect(suites):
    for suite in suites:
        for spec in suite.get("specs", []):
            title = spec.get("title", "")
            if title.startswith("KCARD-LIVE"):
                for test in spec.get("tests", []):
                    observed.append((title, test.get("status"), test.get("expectedStatus")))
        collect(suite.get("suites", []))
collect(report.get("suites", []))
expected_titles = {
    "KCARD-LIVE:",
    "KCARD-LIVE-MUTATION:",
    "KCARD-LIVE-ISOLATION:",
}
if len(observed) != 3 or any(status != "expected" or expected != "passed" for _, status, expected in observed):
    raise SystemExit("Card Studio scenarios did not all pass exactly once")
if not all(any(title.startswith(prefix) for title, _, _ in observed) for prefix in expected_titles):
    raise SystemExit("Required KCARD scenario set is incomplete")
print("Three clean passing KCARD Chromium scenarios; zero skips, retries or unexpected failures")
PY

  run card_studio_local_provenance_after python scripts/ci/verify_local_card_studio_acceptance.py \
    --sha "$ACTUAL_SHA" --project "$KCARD_COMPOSE_PROJECT" --base-url "$KAREN_BASE_URL" \
    --env-file "${KCARD_ACCEPTANCE_ENV_FILE:?Disposable acceptance env file required}" \
    --evidence "$OUT/card-studio-after.json"
fi

printf 'NOT_VERIFIED visual pixel parity and release readiness require independent review.\n' | tee -a "$RESULTS"
printf 'RESULTS=%s\n' "$RESULTS"
