#!/usr/bin/env bash
# Read-only local runtime status. No credentials, guessed models, or hidden fallbacks.
set -euo pipefail

API_ORIGIN="${KAREN_LOCAL_API_ORIGIN:-http://127.0.0.1:8000}"
WEB_ORIGIN="${KAREN_LOCAL_WEB_ORIGIN:-http://127.0.0.1:8010}"

require_loopback_origin() {
  if [[ ! "$1" =~ ^http://(127[.]0[.]0[.]1|localhost):([1-9][0-9]{0,4})$ ]]; then
    printf 'ERROR: Status probes require a loopback HTTP origin with no path or credentials.\n' >&2
    exit 2
  fi
  local port="${BASH_REMATCH[2]}"
  if (( 10#$port > 65535 )); then
    printf 'ERROR: Status probe port is invalid.\n' >&2
    exit 2
  fi
}

require_loopback_origin "$API_ORIGIN"
require_loopback_origin "$WEB_ORIGIN"
command -v curl >/dev/null 2>&1 || { printf 'ERROR: curl is required.\n' >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { printf 'ERROR: python3 is required.\n' >&2; exit 2; }

printf 'Karen local runtime status (read-only)\n'
if ! curl --fail --silent --max-time 8 --output /dev/null "$API_ORIGIN/health/live"; then
  printf 'API liveness: UNAVAILABLE\n'
  printf 'First-run state: UNVERIFIED\n'
  printf 'Model generation: UNVERIFIED\n'
  exit 1
fi
printf 'API liveness: REACHABLE (not a readiness or inference proof)\n'

# The backend owns installation state. A successful HTTP status without a
# boolean first_run_required is not evidence of a usable installation.
first_run_state="$(
  curl --fail --silent --max-time 8 "$API_ORIGIN/api/auth/first-run" |
  python3 -c '
import json
import sys
try:
    payload = json.load(sys.stdin)
    required = payload.get("first_run_required") if isinstance(payload, dict) else None
    if type(required) is not bool:
        raise ValueError("unexpected first-run contract")
    print("BOOTSTRAP_REQUIRED" if required else "CONFIGURED")
except (ValueError, UnicodeError):
    sys.exit(1)
'
)" || {
  printf 'First-run state: UNAVAILABLE (schema/auth readiness not proven)\n'
  printf 'Model generation: UNVERIFIED\n'
  exit 1
}
printf 'First-run state: %s\n' "$first_run_state"

if curl --fail --silent --max-time 8 --output /dev/null "$WEB_ORIGIN/"; then
  printf 'Web ingress: REACHABLE (not a signed-in chat proof)\n'
else
  printf 'Web ingress: UNAVAILABLE\n'
  printf 'Model generation: UNVERIFIED (requires real provider execution and receipt)\n'
  printf 'CopilotKit first turn/replay: UNVERIFIED (requires signed-in browser acceptance)\n'
  exit 1
fi

printf 'Model generation: UNVERIFIED (requires real provider execution and receipt)\n'
printf 'CopilotKit first turn/replay: UNVERIFIED (requires signed-in browser acceptance)\n'

