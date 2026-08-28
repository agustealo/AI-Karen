#!/usr/bin/env bash
set -euo pipefail

# Real fresh-worker production boot proof.
#
# This script owns the container-level smoke contract. It intentionally uses the
# production API image and canonical Supabase migrations rather than importing
# application services directly. The beta workflow and ad-hoc CI can call this
# same script without creating a second test implementation.

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
REPLAY_EMAIL="beta-smoke-replay@example.invalid"
BASE_URL="http://127.0.0.1:${HOST_PORT}"
COOKIE_JAR="$(mktemp)"
API_LOG="$(mktemp)"
REPLAY_BODY="$(mktemp)"

cleanup() {
  rm -f "${COOKIE_JAR}" "${API_LOG}" "${REPLAY_BODY}"
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail_with_api_logs() {
  echo "production first-boot smoke failed" >&2
  docker logs "${API_CONTAINER}" >&2 2>/dev/null || true
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

start_api() {
  : >"${API_LOG}"
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${API_CONTAINER}" \
    --network "${NETWORK}" \
    -p "127.0.0.1:${HOST_PORT}:8000" \
    "${api_env[@]}" \
    "${API_IMAGE}" >/dev/null

  if ! wait_for_command "production API liveness" 90 curl -fsS "${BASE_URL}/health/live"; then
    fail_with_api_logs
  fi

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

echo "[smoke] proving empty installation reports first-run"
first_run_json="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
python3 - "${first_run_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("first_run_required") is True, payload
PY

echo "[smoke] creating and authenticating first durable owner"
setup_json="$(curl -fsS \
  -c "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"confirm_password\":\"${ADMIN_PASSWORD}\",\"full_name\":\"${ADMIN_NAME}\"}" \
  "${BASE_URL}/api/auth/first-run/setup")"
python3 - "${setup_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
user = payload.get("user") or {}
assert payload.get("access_token"), payload
assert payload.get("refresh_token"), payload
assert user.get("tenant_id"), payload
assert user.get("username"), payload
assert "admin" in [str(role).lower() for role in user.get("roles", [])], payload
PY

echo "[smoke] proving setup is one-time and account is queryable"
post_setup_json="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
python3 - "${post_setup_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("first_run_required") is False, payload
PY

replay_status="$(curl -sS \
  -o "${REPLAY_BODY}" \
  -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${REPLAY_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"confirm_password\":\"${ADMIN_PASSWORD}\",\"full_name\":\"Replay Owner\"}" \
  "${BASE_URL}/api/auth/first-run/setup")"
if [[ "${replay_status}" == "200" || "${replay_status}" == "201" ]]; then
  echo "first-run bootstrap replay unexpectedly succeeded" >&2
  cat "${REPLAY_BODY}" >&2
  fail_with_api_logs
fi

me_json="$(curl -fsS -b "${COOKIE_JAR}" "${BASE_URL}/api/auth/me")"
python3 - "${me_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("tenant_id"), payload
assert payload.get("username"), payload
assert payload.get("authenticated") is True, payload
PY

echo "[smoke] restarting exact production image"
docker rm -f "${API_CONTAINER}" >/dev/null
start_api

echo "[smoke] proving durable owner survives process restart"
post_restart_first_run="$(curl -fsS "${BASE_URL}/api/auth/first-run")"
python3 - "${post_restart_first_run}" <<'PY'
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
python3 - "${login_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
user = payload.get("user") or {}
assert payload.get("access_token"), payload
assert user.get("tenant_id"), payload
assert user.get("username"), payload
PY

me_after_restart="$(curl -fsS -b "${COOKIE_JAR}" "${BASE_URL}/api/auth/me")"
python3 - "${me_after_restart}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload.get("tenant_id"), payload
assert payload.get("authenticated") is True, payload
PY

echo "PRODUCTION FIRST-BOOT SMOKE PASSED"
