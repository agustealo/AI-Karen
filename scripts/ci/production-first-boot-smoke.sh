#!/usr/bin/env bash
set -euo pipefail

# Real fresh-worker production boot proof.
#
# This script owns the container-level first-run smoke contract. It intentionally
# uses the production API image, canonical Supabase migrations, a fresh database,
# and password-protected Redis rather than importing application services directly.
# The beta workflow and ad-hoc CI can call this same script without creating a
# second bootstrap implementation.

API_IMAGE="${KAREN_SMOKE_API_IMAGE:-ai-karen-api:beta}"
POSTGRES_IMAGE="${KAREN_SMOKE_POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
REDIS_IMAGE="${KAREN_SMOKE_REDIS_IMAGE:-redis:7-alpine}"
HOST_PORT="${KAREN_SMOKE_API_PORT:-18000}"
SMOKE_ID="${GITHUB_RUN_ID:-local}-$$"
NETWORK="karen-beta-smoke-${SMOKE_ID}"
POSTGRES_CONTAINER="karen-beta-postgres-${SMOKE_ID}"
REDIS_CONTAINER="karen-beta-redis-${SMOKE_ID}"
API_CONTAINER="karen-beta-api-${SMOKE_ID}"
DB_NAME="karen_beta_smoke"
DB_USER="postgres"
DB_PASSWORD="BetaSmokeDb_9f7b3e2a"
REDIS_PASSWORD="BetaSmokeRedis_51d8a3c4"
JWT_SECRET="beta-smoke-jwt-7a94c120f6dd4a9cab3bb6c1c2f58a1d"
APP_SECRET="beta-smoke-app-72f3c8d9442e4c87a28a915bd63fc2cc"
EXTENSION_SECRET="beta-smoke-ext-9f3c1ad483204d30a4fa6ef531b6f42d"
ADMIN_EMAIL="beta-smoke-admin@example.invalid"
ADMIN_PASSWORD="BetaSmoke!Pass9Z"
ADMIN_NAME="Beta Smoke Owner"
BASE_URL="http://127.0.0.1:${HOST_PORT}"
COOKIE_JAR="$(mktemp)"
API_LOG="$(mktemp)"
DUPLICATE_BODY="$(mktemp)"
LIVE_MODEL_BASE_URL="${KAREN_SMOKE_LIVE_MODEL_BASE_URL:-}"
LIVE_MODEL_PROVIDER="${KAREN_SMOKE_LIVE_MODEL_PROVIDER:-lmstudio-desktop}"
LIVE_MODEL_NAME="${KAREN_SMOKE_LIVE_MODEL_NAME:-}"
LIVE_MODEL_TIMEOUT_SECONDS="${KAREN_SMOKE_LIVE_MODEL_TIMEOUT_SECONDS:-90}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "python is required for the production smoke harness" >&2
  exit 1
fi

cleanup() {
  rm -f "${COOKIE_JAR}" "${API_LOG}" "${DUPLICATE_BODY}"
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail_with_api_logs() {
  echo "production first-run smoke failed" >&2
  docker inspect "${API_CONTAINER}" --format='status={{.State.Status}} exit_code={{.State.ExitCode}} error={{.State.Error}}' >&2 || true
  docker logs "${API_CONTAINER}" >&2 || true
  exit 1
}

wait_for_command() {
  local description="$1"
  local attempts="$2"
  shift 2
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "timed out waiting for ${description}" >&2
  return 1
}

api_env=(
  -e ENVIRONMENT=production
  -e DEBUG=false
  -e AUTH_DEV_MODE=false
  -e AUTH_ALLOW_DEV_LOGIN=false
  -e KARI_AUTH_BYPASS=false
  -e AUTH_ENABLE_SESSION_VALIDATION=true
  -e AUTH_AUTO_CREATE_TABLES=false
  -e AUTH_JWT_SECRET_KEY="${JWT_SECRET}"
  -e AUTH_SECRET_KEY="${APP_SECRET}"
  -e SECRET_KEY="${APP_SECRET}"
  -e EXTENSION_SECRET_KEY="${EXTENSION_SECRET}"
  -e EXTENSION_API_KEY="${EXTENSION_SECRET}"
  -e EXTENSION_DEV_BYPASS_ENABLED=false
  -e KARI_DUCKDB_PASSWORD="BetaSmokeDuckDb_6f2a1d93"
  -e KARI_JOB_ENC_KEY="YmV0YS1zbW9rZS1qb2ItZW5jLWtleS0zMi1ieXRlISE="
  -e KARI_JOB_SIGNING_KEY="beta-smoke-job-sign-54c6a781d2e34f7ba90c13d8e5f624ab"
  -e KARI_MODEL_SIGNING_KEY="beta-smoke-model-sign-7e4a2c98f1364db5b0a7c21d9e6f83ab"
  -e KARI_FAST_STARTUP=false
  -e KARI_SKIP_STARTUP_CHECK=false
  -e KARI_SKIP_AUTO_INIT=false
  -e KARI_DEFER_ROUTER_WIRING=false
  -e KAREN_BUILTIN_VLLM_ENABLED=false
  -e WARMUP_LLM=false
  -e DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e POSTGRES_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e AUTH_DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e POSTGRES_HOST="${POSTGRES_CONTAINER}"
  -e POSTGRES_PORT=5432
  -e POSTGRES_USER="${DB_USER}"
  -e POSTGRES_PASSWORD="${DB_PASSWORD}"
  -e POSTGRES_DB="${DB_NAME}"
  -e DB_HOST="${POSTGRES_CONTAINER}"
  -e DB_PORT=5432
  -e DB_USER="${DB_USER}"
  -e DB_PASSWORD="${DB_PASSWORD}"
  -e DB_NAME="${DB_NAME}"
  -e DATABASE_PASSWORD="${DB_PASSWORD}"
  -e SSL_MODE=prefer
  -e REDIS_PASSWORD="${REDIS_PASSWORD}"
  -e REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_CONTAINER}:6379/0"
  -e REDIS_HOST="${REDIS_CONTAINER}"
  -e REDIS_PORT=6379
)

if [[ -n "${LIVE_MODEL_BASE_URL}" ]]; then
  container_model_url="$("${PYTHON_BIN}" - "${LIVE_MODEL_BASE_URL}" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

raw = sys.argv[1].strip().rstrip("/")
parts = urlsplit(raw)
if (parts.hostname or "") in {"127.0.0.1", "localhost"}:
    netloc = "host.docker.internal"
    if parts.port:
        netloc += f":{parts.port}"
    parts = parts._replace(netloc=netloc)
print(urlunsplit(parts))
PY
)"
  case "${LIVE_MODEL_PROVIDER}" in
    lmstudio-desktop)
      api_env+=( -e LMSTUDIO_BASE_URL="${container_model_url}" )
      ;;
    ollama-local)
      api_env+=( -e OLLAMA_BASE_URL="${container_model_url}" )
      ;;
    llamacpp-server)
      api_env+=( -e LLAMACPP_BASE_URL="${container_model_url}" )
      ;;
    *)
      echo "unsupported production live-model provider: ${LIVE_MODEL_PROVIDER}" >&2
      exit 1
      ;;
  esac
fi

start_api() {
  : >"${API_LOG}"
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${API_CONTAINER}" \
    --network "${NETWORK}" \
    --add-host "host.docker.internal:host-gateway" \
    -p "127.0.0.1:${HOST_PORT}:8000" \
    "${api_env[@]}" \
    "${API_IMAGE}" >/dev/null

  for ((attempt = 1; attempt <= 90; attempt++)); do
    if curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; then
      break
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "${API_CONTAINER}" 2>/dev/null || echo false)" != "true" ]]; then
      echo "production API container exited before liveness" >&2
      fail_with_api_logs
    fi
    if [[ "${attempt}" -eq 90 ]]; then
      echo "timed out waiting for production API liveness" >&2
      fail_with_api_logs
    fi
    sleep 2
  done

  if ! wait_for_command "production auth readiness" 30 curl -fsS "${BASE_URL}/api/auth/health"; then
    fail_with_api_logs
  fi
}

echo "[smoke] creating isolated Docker network"
docker network create "${NETWORK}" >/dev/null

echo "[smoke] starting fresh PostgreSQL + pgvector"
docker run -d \
  --name "${POSTGRES_CONTAINER}" \
  --network "${NETWORK}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB="${DB_NAME}" \
  "${POSTGRES_IMAGE}" >/dev/null

if ! wait_for_command "PostgreSQL" 45 docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}"; then
  docker logs "${POSTGRES_CONTAINER}" >&2 || true
  exit 1
fi

echo "[smoke] starting password-protected Redis"
docker run -d \
  --name "${REDIS_CONTAINER}" \
  --network "${NETWORK}" \
  "${REDIS_IMAGE}" \
  redis-server --requirepass "${REDIS_PASSWORD}" >/dev/null

if ! wait_for_command "Redis" 30 docker exec "${REDIS_CONTAINER}" redis-cli -a "${REDIS_PASSWORD}" ping; then
  docker logs "${REDIS_CONTAINER}" >&2 || true
  exit 1
fi

echo "[smoke] applying canonical migrations to an empty database"
while IFS= read -r migration; do
  echo "[smoke] migration $(basename "${migration}")"
  docker exec -i "${POSTGRES_CONTAINER}" \
    psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" <"${migration}"
done < <(find supabase/migrations -maxdepth 1 -type f -name '*.sql' | sort)

echo "[smoke] booting production API image"
start_api

echo "[smoke] rejecting known first-boot startup wiring faults"
startup_logs="$(docker logs "${API_CONTAINER}" 2>&1 || true)"
if grep -Fq "'PromptRegistry' object has no attribute 'get'" <<<"${startup_logs}"; then
  echo "extension discovery used retired PromptRegistry.get API" >&2
  fail_with_api_logs
fi
if grep -Fq "name 'RobotsPolicy' is not defined" <<<"${startup_logs}"; then
  echo "Crawl4AI started without RobotsPolicy wiring" >&2
  fail_with_api_logs
fi

echo "[smoke] proving empty installation reports first-run"
first_run_json="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
"${PYTHON_BIN}" - "${first_run_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("first_run_required") is True, payload
assert payload.get("message") == "First-run setup required", payload
PY

echo "[smoke] creating and authenticating first durable owner"
setup_json="$(curl -fsS \
  -c "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"confirm_password\":\"${ADMIN_PASSWORD}\",\"full_name\":\"${ADMIN_NAME}\"}" \
  "${BASE_URL}/api/auth/first-run/setup")"
"${PYTHON_BIN}" - "${setup_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
user = payload.get("user") or {}
assert payload.get("access_token"), payload
assert payload.get("refresh_token"), payload
assert user.get("tenant_id"), payload
assert user.get("username"), payload
assert "admin" in [str(role).lower() for role in user.get("roles", [])], payload
assert "user" in [str(role).lower() for role in user.get("roles", [])], payload
PY

echo "[smoke] proving bootstrap is one-time"
duplicate_status="$(curl -sS \
  -o "${DUPLICATE_BODY}" \
  -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"duplicate@example.invalid\",\"password\":\"${ADMIN_PASSWORD}\",\"confirm_password\":\"${ADMIN_PASSWORD}\",\"full_name\":\"Duplicate Owner\"}" \
  "${BASE_URL}/api/auth/first-run/setup")"
if [[ "${duplicate_status}" != "400" ]]; then
  cat "${DUPLICATE_BODY}" >&2 || true
  echo "expected duplicate first-run setup to return HTTP 400, got ${duplicate_status}" >&2
  fail_with_api_logs
fi

admin_count="$(docker exec "${POSTGRES_CONTAINER}" \
  psql -At -U "${DB_USER}" -d "${DB_NAME}" \
  -c "SELECT COUNT(*) FROM auth_users;")"
if [[ "${admin_count}" != "1" ]]; then
  echo "expected exactly one durable bootstrap user, got ${admin_count}" >&2
  exit 1
fi

tenant_count="$(docker exec "${POSTGRES_CONTAINER}" \
  psql -At -U "${DB_USER}" -d "${DB_NAME}" \
  -c "SELECT COUNT(*) FROM tenants WHERE is_active = TRUE;")"
if [[ "${tenant_count}" -lt "1" ]]; then
  echo "expected at least one active durable tenant" >&2
  exit 1
fi

echo "[smoke] proving setup state and authenticated identity are queryable"
post_setup_json="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
"${PYTHON_BIN}" - "${post_setup_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("first_run_required") is False, payload
assert payload.get("message") == "System already configured", payload
PY

me_json="$(curl -fsS -b "${COOKIE_JAR}" "${BASE_URL}/api/auth/me")"
"${PYTHON_BIN}" - "${me_json}" "${ADMIN_EMAIL}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
expected_email = sys.argv[2]
roles = {str(role).lower() for role in payload.get("roles", [])}
assert payload.get("user_id"), payload
assert payload.get("email") == expected_email, payload
assert payload.get("tenant_id"), payload
assert payload.get("username"), payload
assert {"admin", "user"}.issubset(roles), payload
PY

echo "[smoke] restarting exact production image"
docker rm -f "${API_CONTAINER}" >/dev/null
start_api

echo "[smoke] proving durable owner and completed first-run state survive restart"
post_restart_first_run="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
"${PYTHON_BIN}" - "${post_restart_first_run}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("first_run_required") is False, payload
PY

login_json="$(curl -fsS \
  -c "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  "${BASE_URL}/api/auth/login")"
"${PYTHON_BIN}" - "${login_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
user = payload.get("user") or {}
assert payload.get("access_token"), payload
assert user.get("tenant_id"), payload
assert user.get("username"), payload
assert "admin" in [str(role).lower() for role in user.get("roles", [])], payload
PY

me_after_restart="$(curl -fsS -b "${COOKIE_JAR}" "${BASE_URL}/api/auth/me")"
"${PYTHON_BIN}" - "${me_after_restart}" "${ADMIN_EMAIL}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
expected_email = sys.argv[2]
roles = {str(role).lower() for role in payload.get("roles", [])}
assert payload.get("user_id"), payload
assert payload.get("email") == expected_email, payload
assert payload.get("tenant_id"), payload
assert payload.get("username"), payload
assert {"admin", "user"}.issubset(roles), payload
PY

if [[ -n "${LIVE_MODEL_BASE_URL}" ]]; then
  echo "[smoke] proving two-turn ChatRuntime execution against configured live model"
  live_session="beta_live_${GITHUB_RUN_ID:-local}_$"
  live_token="KAREN_${GITHUB_RUN_ID:-local}_$_CONTINUITY"

  first_payload="$("${PYTHON_BIN}" - "${live_session}" "${LIVE_MODEL_PROVIDER}" "${LIVE_MODEL_NAME}" "${live_token}" <<'PY'
import json
import sys

session_id, provider, model, token = sys.argv[1:5]
payload = {
    "messages": [{
        "content": (
            "Remember this exact release token for the next turn: "
            f"{token}. Reply briefly and include the token exactly once."
        ),
        "message_type": "user",
    }],
    "preferred_llm_provider": provider,
    "temperature": 0.0,
    "max_tokens": 96,
    "stream": False,
    "session_id": session_id,
}
if model:
    payload["preferred_model"] = model
print(json.dumps(payload))
PY
)"

  first_response="$(curl -fsS --max-time "${LIVE_MODEL_TIMEOUT_SECONDS}" \
    -b "${COOKIE_JAR}" \
    -H 'Content-Type: application/json' \
    -d "${first_payload}" \
    "${BASE_URL}/api/chat")"

  "${PYTHON_BIN}" - "${first_response}" "${LIVE_MODEL_PROVIDER}" "${LIVE_MODEL_NAME}" "${live_token}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_provider, expected_model, token = sys.argv[2:5]
content = str(payload.get("content") or "")
metadata = payload.get("metadata") or {}
assert content, payload
assert token in content, payload
assert payload.get("model") not in {None, "", "unknown"}, payload
assert metadata.get("actual_provider") == expected_provider, metadata
assert metadata.get("response_source") not in {"emergency", "unavailable"}, metadata
if expected_model:
    actual_model = str(metadata.get("actual_model") or payload.get("model") or "")
    assert actual_model, metadata
PY

  second_payload="$("${PYTHON_BIN}" - "${live_session}" "${LIVE_MODEL_PROVIDER}" "${LIVE_MODEL_NAME}" <<'PY'
import json
import sys

session_id, provider, model = sys.argv[1:4]
payload = {
    "messages": [{
        "content": (
            "What exact release token did I ask you to remember in the previous turn? "
            "Reply with that token and nothing else."
        ),
        "message_type": "user",
    }],
    "preferred_llm_provider": provider,
    "temperature": 0.0,
    "max_tokens": 64,
    "stream": False,
    "session_id": session_id,
}
if model:
    payload["preferred_model"] = model
print(json.dumps(payload))
PY
)"

  second_response="$(curl -fsS --max-time "${LIVE_MODEL_TIMEOUT_SECONDS}" \
    -b "${COOKIE_JAR}" \
    -H 'Content-Type: application/json' \
    -d "${second_payload}" \
    "${BASE_URL}/api/chat")"

  "${PYTHON_BIN}" - "${second_response}" "${LIVE_MODEL_PROVIDER}" "${live_token}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_provider, token = sys.argv[2:4]
content = str(payload.get("content") or "").strip()
metadata = payload.get("metadata") or {}
assert token in content, payload
assert metadata.get("actual_provider") == expected_provider, metadata
assert metadata.get("response_source") not in {"emergency", "unavailable"}, metadata
PY

  transcript_json="$(curl -fsS -b "${COOKIE_JAR}" \
    "${BASE_URL}/api/conversations/by-session/${live_session}")"

  "${PYTHON_BIN}" - "${transcript_json}" "${live_token}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
token = sys.argv[2]
messages = payload.get("messages") or []
assert payload.get("message_count") == len(messages), payload
assert len(messages) >= 4, payload
roles = [str(message.get("role") or "").lower() for message in messages[-4:]]
assert roles == ["user", "assistant", "user", "assistant"], roles
assert token in str(messages[-4].get("content") or ""), messages[-4]
assert token in str(messages[-1].get("content") or ""), messages[-1]
PY

  echo "PRODUCTION LIVE-MODEL TWO-TURN CHAT PROOF PASSED"
fi

echo "PRODUCTION FIRST-RUN SMOKE PASSED"