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

# Explorer write trials require a dedicated local-only invocation.
if [[ "${RUN_FILE_EXPLORER_LOCAL:-0}" == '1' ]]; then
  [[ "${RUN_BROWSER:-0}" != '1' && "${RUN_CARD_STUDIO_LOCAL:-0}" != '1' ]] || {
    echo 'Run Explorer acceptance separately from other browser modes.' >&2; exit 2;
  }
  [[ "${GITHUB_ACTIONS:-false}" != 'true' && ! -v VERCEL_AUTOMATION_BYPASS_SECRET ]] || {
    echo 'Explorer requires local execution without Vercel credentials.' >&2; exit 2;
  }
  [[ "${KAREN_BASE_URL:-}" == 'http://127.0.0.1:8010' &&
     "${KAREN_LOCAL_CHAT_ACCEPTANCE:-0}" == '1' &&
     "${KAREN_CHAT_BOOT_ACCEPTANCE:-0}" != '1' &&
     "${KAREN_SANITIZED_ACCOUNT:-false}" == 'true' ]] || {
    echo 'Explicit approved local origin and sanitized identities required.' >&2; exit 2;
  }
  for flag in KAREN_SETTINGS_VERIFIED_DEPLOYMENT KAREN_SEARCH_ACCEPTANCE_REQUIRED \
      KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED; do
    [[ "${!flag:-false}" != 'true' ]] || {
      echo 'Protected deployment flags are forbidden in Explorer local acceptance.' >&2; exit 2;
    }
  done
  for flag in KAREN_FILE_EXPLORER_ACCEPTANCE KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE \
      KAREN_FILE_EXPLORER_REQUIRE_NESTED KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED \
      KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE \
      KAREN_FILE_EXPLORER_ATTACHMENT_ACCEPTANCE KAREN_FILE_EXPLORER_ISOLATION_ACCEPTANCE; do
    [[ "${!flag:-false}" == 'true' ]] || {
      printf 'Missing explicit Explorer approval: %s\n' "$flag" >&2; exit 2;
    }
  done
  : "${KAREN_UX_EMAIL:?Dedicated owner email required}"
  : "${KAREN_UX_PASSWORD:?Dedicated owner password required}"
  : "${KAREN_UX_ISOLATION_EMAIL:?Dedicated isolation email required}"
  : "${KAREN_UX_ISOLATION_PASSWORD:?Dedicated isolation password required}"
  [[ "${KAREN_UX_EMAIL,,}" != "${KAREN_UX_ISOLATION_EMAIL,,}" ]] || {
    echo 'Two distinct sanitized accounts are required.' >&2; exit 2;
  }
  : "${KAREN_FILE_EXPLORER_ATTACHMENT_CONVERSATION_TITLE:?Disposable conversation title required}"
  : "${KCARD_COMPOSE_PROJECT:?Dedicated existing local Compose project required}"
  : "${KCARD_ACCEPTANCE_ENV_FILE:?Private existing local acceptance env file required}"
  ids=()
  for key in KAREN_FILE_EXPLORER_MUTATION_FIXTURE_ID \
      KAREN_FILE_EXPLORER_ATTACHMENT_CONVERSATION_ID \
      KAREN_FILE_EXPLORER_ISOLATION_A_SOURCE_ID KAREN_FILE_EXPLORER_ISOLATION_A_FOLDER_ID \
      KAREN_FILE_EXPLORER_ISOLATION_A_CONVERSATION_ID \
      KAREN_FILE_EXPLORER_ISOLATION_B_SOURCE_ID KAREN_FILE_EXPLORER_ISOLATION_B_FOLDER_ID \
      KAREN_FILE_EXPLORER_ISOLATION_B_CONVERSATION_ID; do
    value="${!key:-}"
    [[ "$value" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || {
      printf 'Invalid disposable fixture UUID: %s\n' "$key" >&2; exit 2;
    }
    ids+=("${value,,}")
  done
  [[ "$(printf '%s\n' "${ids[@]}" | sort -u | wc -l)" -eq 8 ]] || {
    echo 'Explorer fixtures must be distinct.' >&2; exit 2;
  }
fi

# Authenticated reports may contain live metadata. Keep outside the checkout.
OUT="${KAREN_KUI_ACCEPTANCE_OUTPUT_DIR:-${XDG_STATE_HOME:-${HOME:?}/.local/state}/ai-karen/kui-acceptance/$ACTUAL_SHA}"
if [[ "${RUN_FILE_EXPLORER_LOCAL:-0}" == '1' ]]; then
  OUT="$(python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]).resolve(); r=pathlib.Path(sys.argv[2]).resolve(); sys.exit("Evidence must be outside checkout") if p.is_relative_to(r) else print(p)' "$OUT" "$ROOT")"
  mkdir -p "$OUT"
  OUT="$(mktemp -d "$OUT/explorer.XXXXXXXX")"
else
  mkdir -p "$OUT"
fi
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

if [[ "${RUN_FILE_EXPLORER_LOCAL:-0}" == '1' ]]; then
  PROVENANCE=(python "$ROOT/scripts/ci/verify_local_card_studio_acceptance.py"
    --file-explorer --sha "$ACTUAL_SHA" --project "$KCARD_COMPOSE_PROJECT"
    --base-url "$KAREN_BASE_URL" --env-file "$KCARD_ACCEPTANCE_ENV_FILE")
  REPORT=(python "$ROOT/scripts/ci/verify_local_browser_report.py")
  run explorer_provenance_before "${PROVENANCE[@]}" --evidence "$OUT/explorer-before.json"

  cd "$ROOT/src/ui_launchers/Karen-AI-Theme"
  run explorer_npm_install env -u KAREN_UX_EMAIL -u KAREN_UX_PASSWORD \
    -u KAREN_UX_ISOLATION_EMAIL -u KAREN_UX_ISOLATION_PASSWORD npm ci
  run explorer_chromium_install env -u KAREN_UX_EMAIL -u KAREN_UX_PASSWORD \
    -u KAREN_UX_ISOLATION_EMAIL -u KAREN_UX_ISOLATION_PASSWORD npx playwright install chromium
  BROWSER=(npx playwright test e2e/file-explorer-real-acceptance.spec.ts
    --config=e2e/playwright.config.ts --project=chromium
    --grep='\bKFILE-(LIVE|MUTATION-LOCAL|ATTACHMENT-LOCAL|ISOLATION-LOCAL):'
    --workers=1 --retries=0 --forbid-only --reporter=json
    --output="$OUT/playwright-artifacts")
  run explorer_discover env -u PW_TEST_REPORTER -u PLAYWRIGHT_JSON_ONLY_FAILURES \
    CI=1 PLAYWRIGHT_JSON_OUTPUT_FILE="$OUT/explorer-list.json" "${BROWSER[@]}" --list
  run explorer_discovery_evidence "${REPORT[@]}" "$OUT/explorer-list.json" --list-only
  cd "$ROOT"
  [[ "$(git rev-parse HEAD)" == "$ACTUAL_SHA" && -z "$(git status --porcelain)" ]] || {
    echo 'Checkout changed during acceptance preparation.' >&2; exit 2;
  }
  run explorer_provenance_pre_execution "${PROVENANCE[@]}" --evidence "$OUT/explorer-pre-execution.json"
  cd "$ROOT/src/ui_launchers/Karen-AI-Theme"
  run explorer_live_browser env -u PW_TEST_REPORTER -u PLAYWRIGHT_JSON_ONLY_FAILURES \
    CI=1 PLAYWRIGHT_JSON_OUTPUT_FILE="$OUT/explorer-playwright.json" "${BROWSER[@]}"
  run explorer_browser_evidence "${REPORT[@]}" "$OUT/explorer-playwright.json"
  cd "$ROOT"
  run explorer_provenance_after "${PROVENANCE[@]}" --evidence "$OUT/explorer-after.json"
  run explorer_provenance_continuity python - \
    "$OUT/explorer-before.json" "$OUT/explorer-pre-execution.json" "$OUT/explorer-after.json" <<'PY'
import json
import sys
from pathlib import Path

records = [json.loads(Path(path).read_text()) for path in sys.argv[1:]]
for record in records:
    record.pop("timestamp", None)
if any(record != records[0] for record in records[1:]):
    raise SystemExit("Local stack identity changed during Explorer acceptance")
print("Explorer stack identity remained consistent across recorded checkpoints")
PY
  [[ "$(git rev-parse HEAD)" == "$ACTUAL_SHA" && -z "$(git status --porcelain)" ]] || {
    echo 'Checkout changed during acceptance.' >&2; exit 2;
  }
  printf 'PASS explorer_local_acceptance (four scenarios; independent review still required)\n' | tee -a "$RESULTS"
  printf 'RESULTS=%s\n' "$RESULTS"
  exit 0
fi

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
